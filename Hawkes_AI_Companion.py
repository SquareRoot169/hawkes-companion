"""Hawkes AI Companion v0.7. Local tutoring and a LaTeX PDF Studio."""
import ast
import base64
import io
import json
import math
import queue
import re
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from urllib import request

import numpy as np
from PIL import Image, ImageGrab, ImageTk, ImageOps, ImageDraw
from matplotlib.figure import Figure
from hawkes_renderer import RenderWorker
from hawkes_pdf import PdfExportWorker, FOLDER_NAME
from hawkes_pdf_studio import PdfStudio
from hawkes_speech import SpeechWorker, VOICES, PREVIEW
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

URL = 'http://127.0.0.1:11434/api'
VISION_MODEL = 'qwen3-vl:8b'
STYLES = {
    'Socratic': 'Guide the student by asking ONE focused question at a time. Do not give the final answer unless explicitly requested. Respond constructively to attempts.',
    'Feynman-inspired': 'Explain mathematics with everyday language, concrete analogies and intuition, inspired by Richard Feynman\u2019s educational approach. Do not claim to be Feynman or imitate his exact voice.',
    'Traditional professor': 'Teach with precise definitions, correct mathematical notation, justified steps and concise worked examples. Adapt to the student\u2019s level.'
}
SYSTEM = r'''You are a patient mathematics tutor accompanying a separate algebra program.
Develop understanding. Only see images explicitly attached to this conversation; never claim live screen access.
If an image is unclear, ask for a clearer crop. Check arithmetic carefully.
Write ALL mathematical expressions in LaTeX delimited by $...$ or $$...$$ (also supported: \(...\), \[...\]).
Use standard LaTeX including fractions, boxed results, matrices, aligned equations and cases.
Use Markdown headings, emphasis and lists where helpful. Put multiline math inside $$...$$ or \[...\].
Do not put math in code fences. For graphs, explain the expression to enter in the Graph window using x, ^, sin(x), etc.
Teaching style: '''

def encode_image(image):
    image = ImageOps.exif_transpose(image).convert('RGB')
    image.thumbnail((2048, 2048))
    stream = io.BytesIO()
    image.save(stream, 'PNG')
    return base64.b64encode(stream.getvalue()).decode('ascii')


# Parse only a small arithmetic language; never execute user/model Python.
FUNCS = {name: getattr(np, name) for name in ('sin', 'cos', 'tan', 'sqrt', 'exp', 'log', 'log10', 'abs', 'arcsin', 'arccos', 'arctan')}
FUNCS['ln'] = np.log


def evaluate(expression, x):
    expression = expression.strip()
    if expression.startswith('y=') or expression.startswith('y ='):
        expression = expression.split('=', 1)[1].strip()
    if len(expression) > 500:
        raise ValueError('Expression is too long.')
    tree = ast.parse(expression.replace('^', '**'), mode='eval')
    if sum(1 for _ in ast.walk(tree)) > 120:
        raise ValueError('Expression is too complex.')

    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            if not math.isfinite(float(node.value)) or abs(node.value) > 1e100:
                raise ValueError('Number is too large.')
            return float(node.value)
        if isinstance(node, ast.Name) and node.id in ('x', 'pi', 'e'):
            return {'x': x, 'pi': np.pi, 'e': np.e}[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp):
            a, b = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add): return a + b
            if isinstance(node.op, ast.Sub): return a - b
            if isinstance(node.op, ast.Mult): return a * b
            if isinstance(node.op, ast.Div): return np.divide(a, b)
            if isinstance(node.op, ast.Pow):
                if np.any(np.abs(b) > 100):
                    raise ValueError('Exponents must be between -100 and 100.')
                return np.power(a, b)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCS and len(node.args) == 1 and not node.keywords:
            return FUNCS[node.func.id](visit(node.args[0]))
        raise ValueError('Use x, numbers, + - * / ^, parentheses, and supported functions. Example: 2*x^2 - 3')

    with np.errstate(all='ignore'):
        result = np.asarray(visit(tree), dtype=float)
    return np.broadcast_to(result, np.shape(x)).copy()


class GraphWindow:
    def __init__(self, root):
        self.window = tk.Toplevel(root)
        self.window.title('Graph functions — Hawkes Companion')
        self.window.attributes('-topmost', root.attributes('-topmost'))
        self.window.geometry('800x650')
        controls = ttk.Frame(self.window, padding=10)
        controls.pack(fill='x')
        ttk.Label(controls, text='Functions separated by ;   (use * for multiplication)').pack(anchor='w')
        self.expression = ttk.Entry(controls)
        self.expression.insert(0, 'x^2; 2*x + 1')
        self.expression.pack(fill='x', pady=5)
        row = ttk.Frame(controls)
        row.pack(fill='x')
        self.low, self.high = tk.StringVar(value='-10'), tk.StringVar(value='10')
        for label, var in [('x min', self.low), ('x max', self.high)]:
            ttk.Label(row, text=label).pack(side='left', padx=4)
            ttk.Entry(row, textvariable=var, width=9).pack(side='left')
        ttk.Button(row, text='Plot', command=self.plot).pack(side='left', padx=10)
        ttk.Button(row, text='Save PNG', command=self.save).pack(side='left')
        ttk.Label(controls, text='sin cos tan sqrt exp log ln log10 abs arcsin arccos arctan • pi, e\nExample: sqrt(x); sin(x); 1/x   |   Pan and zoom with the toolbar.').pack(anchor='w', pady=5)
        self.figure = Figure(figsize=(7, 4), dpi=100)
        self.axes = self.figure.add_subplot()
        self.canvas = FigureCanvasTkAgg(self.figure, master=self.window)
        self.canvas.get_tk_widget().pack(fill='both', expand=True)
        NavigationToolbar2Tk(self.canvas, self.window)
        self.expression.bind('<Return>', lambda _: self.plot())
        self.plot()

    def plot(self):
        try:
            low, high = float(self.low.get()), float(self.high.get())
            if not (math.isfinite(low) and math.isfinite(high) and -1e6 <= low < high <= 1e6):
                raise ValueError('Choose finite x limits between -1,000,000 and 1,000,000, with min < max.')
            expressions = [s.strip() for s in self.expression.get().split(';') if s.strip()]
            if not 1 <= len(expressions) <= 6:
                raise ValueError('Enter one to six functions.')
            x = np.linspace(low, high, 1601)
            curves = [(s, evaluate(s, x)) for s in expressions]
            if not any(np.isfinite(y).any() for _, y in curves):
                raise ValueError('No real finite values in this interval.')
            self.axes.clear()
            for label, y in curves:
                y[~np.isfinite(y)] = np.nan
                # Break large jumps across sampled asymptotes.
                finite = y[np.isfinite(y)]
                scale = max(1, np.percentile(np.abs(finite), 90)) if finite.size else 1
                jumps = np.flatnonzero(np.abs(np.diff(y)) > 10 * scale)
                y[jumps] = np.nan
                self.axes.plot(x, y, label=label)
            self.axes.axhline(0, color='gray', linewidth=.7)
            self.axes.axvline(0, color='gray', linewidth=.7)
            self.axes.set_xlim(low, high)
            self.axes.set_xlabel('x')
            self.axes.set_ylabel('y')
            self.axes.grid(alpha=.25)
            self.axes.legend()
            self.figure.tight_layout()
            self.canvas.draw()
        except Exception as exc:
            messagebox.showerror('Cannot plot', str(exc), parent=self.window)

    def save(self):
        path = filedialog.asksaveasfilename(parent=self.window, defaultextension='.png', filetypes=[('PNG image', '*.png')])
        if path:
            try: self.figure.savefig(path, dpi=160)
            except Exception as exc: messagebox.showerror('Cannot save', str(exc), parent=self.window)


class RoundedPanel(tk.Canvas):
    """A native Tk content surface with an antialiased rounded outline."""
    def __init__(self, parent, **kwargs):
        super().__init__(parent, background='#f3f6fa', highlightthickness=0,
                         borderwidth=0, height=1, width=1, **kwargs)
        self.inner = tk.Frame(self, bg='white', borderwidth=0)
        self.surface = self.create_window(10, 10, window=self.inner, anchor='nw')
        self.bind('<Configure>', self.layout)
        self.outline = None

    def layout(self, event):
        w, h = max(1, event.width), max(1, event.height)
        if self.outline:
            self.delete(self.outline)
        # Render only the border/background, not any tutor content.
        image = Image.new('RGB', (w*2, h*2), '#f3f6fa')
        ImageDraw.Draw(image).rounded_rectangle((1, 1, w*2-2, h*2-2),
                       radius=28, fill='white', outline='#dbe4ec', width=2)
        self.surface_photo = ImageTk.PhotoImage(image.resize((w, h), Image.Resampling.LANCZOS), master=self)
        self.outline = self.create_image(0, 0, image=self.surface_photo, anchor='nw')
        self.tag_lower(self.outline)
        self.itemconfigure(self.surface, width=max(1,w-20), height=max(1,h-20))


class Companion:
    def __init__(self, root, surface=None):
        self.root = root
        self.closed = False
        self.surface = surface if surface is not None else root
        root.title('Hawkes AI Companion v0.7 — Local Ollama')
        height = min(780, max(480, root.winfo_screenheight()-120))
        width = min(700, max(520, root.winfo_screenwidth()-80))
        root.geometry(f'{width}x{height}')
        root.minsize(min(560, width), min(660, height))
        self.surface.columnconfigure(0, weight=1)
        self.surface.rowconfigure(2, weight=1)
        root.attributes('-topmost', True)
        self.history, self.photos = [], []
        self.attachment_photos = []
        self.pending = None
        self.busy = False
        self.jobs = queue.Queue()
        self.hawk_shell = None
        self.voice_enabled = tk.BooleanVar(value=False)
        self.voice_name = tk.StringVar(value='Heart (female)')
        self.voice_speed = tk.DoubleVar(value=1.0)
        self.voice_note = tk.StringVar(value='Voice off')
        self.speech = SpeechWorker(self.jobs, self.speech_event)
        self.renderer = RenderWorker(self.jobs)
        self.pdf_worker = PdfExportWorker(self.jobs)
        self.pdf_text = None
        self.pdf_busy = False
        self.pdf_folder_override = None
        self.last_pdf = None
        self.pdf_studio = None
        self.graph_window = None
        self.render_id = 0
        self.generation = 0
        self.latest_reply = ""
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.model = tk.StringVar()
        self.style = tk.StringVar(value='Socratic')
        self.status = tk.StringVar(value='Checking Ollama...')
        self.attachment = tk.StringVar(value='No image attached')
        self.topmost = tk.BooleanVar(value=True)
        self.configure_theme()
        header = ttk.Frame(self.surface, padding=(16, 8, 16, 6))
        header.grid(row=0, column=0, sticky='ew')
        ttk.Label(header, text='Hawkes' if surface is not None else 'Hawkes Companion', style='Title.TLabel').pack(side='left')
        ttk.Label(header, text='v0.7  •  LOCAL', style='Muted.TLabel').pack(side='right')
        top = ttk.Frame(self.surface, padding=(16, 0, 16, 8))
        top.grid(row=1, column=0, sticky='ew')
        self.settings_panel = top
        self.settings_auto = surface is not None
        self.settings_visible = True
        if surface is not None:
            self.settings_button = ttk.Button(header, text='Settings ▾', command=self.toggle_settings)
            self.settings_button.pack(side='right', padx=6)
            self.surface.bind('<Configure>', self.adapt_settings)
        for col, text in enumerate(('Teaching style', 'Local text model')):
            ttk.Label(top, text=text, style='Muted.TLabel').grid(row=0, column=col, sticky='w', pady=(0, 5))
            top.columnconfigure(col, weight=1)
        ttk.Combobox(top, textvariable=self.style, values=list(STYLES), state='readonly', width=14).grid(row=1, column=0, sticky='ew', padx=(0, 12))
        self.models = ttk.Combobox(top, textvariable=self.model, width=14)
        self.models.grid(row=1, column=1, sticky='ew')
        ttk.Checkbutton(top, text='Stay on top', variable=self.topmost, command=lambda: root.attributes('-topmost', self.topmost.get())).grid(row=2, column=0, sticky='w', pady=(8, 0))
        ttk.Button(top, text='Refresh models', command=self.refresh).grid(row=2, column=1, sticky='e', pady=(8, 0))
        self.chat_panel = RoundedPanel(self.surface)
        self.chat_panel.grid(row=2, column=0, sticky='nsew', padx=16)
        chat_frame = self.chat_panel.inner
        self.chat = tk.Text(chat_frame, wrap='word', state='disabled', height=1, width=1, padx=8, pady=4,
                            font=('Segoe UI', 11), bg='white', fg='#243247',
                            relief='flat', borderwidth=0, highlightthickness=0,
                            selectbackground='#cce9e7', insertbackground='#137c75')
        scroll = ttk.Scrollbar(chat_frame, command=self.chat.yview)
        self.chat.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.chat.pack(fill='both', expand=True)
        self.horizontal = ttk.Scrollbar(chat_frame, orient='horizontal', command=self.chat.xview)
        self.chat.configure(xscrollcommand=self.update_horizontal)
        self.chat.tag_configure('user', foreground='#137c75', font=('Segoe UI', 11, 'bold'), spacing1=12, spacing3=6)
        self.chat.tag_configure('assistant', foreground='#52647a', font=('Segoe UI', 10, 'bold'), spacing1=12, spacing3=6)
        self.rendered_messages = []
        self.resize_job = None
        self.chat.bind('<Configure>', self.schedule_reflow)
        bottom = ttk.Frame(self.surface, padding=(16, 8, 16, 10))
        bottom.grid(row=3, column=0, sticky='ew')
        tools = ttk.Frame(bottom)
        tools.pack(fill='x', pady=(0, 8))
        ttk.Button(tools, text='Capture region', command=self.capture).pack(side='left')
        ttk.Button(tools, text='Attach image', command=self.attach).pack(side='left', padx=6)
        ttk.Button(tools, text='Graph / visualize', command=self.open_graph).pack(side='left')
        speech_tools = ttk.Frame(bottom)
        speech_tools.pack(fill='x', pady=(0, 6))
        self.voice_toggle = ttk.Checkbutton(speech_tools, text='Voice off', variable=self.voice_enabled,
                                             command=self.toggle_voice)
        self.voice_toggle.pack(side='left')
        self.read_button = ttk.Button(speech_tools, text='Read', command=self.read_reply, state='disabled', width=0)
        self.read_button.pack(side='left', padx=5)
        self.stop_voice_button = ttk.Button(speech_tools, text='Stop', command=self.stop_voice, state='disabled', width=0)
        self.stop_voice_button.pack(side='left')
        ttk.Button(speech_tools, text='Voice options', command=self.voice_options, width=0).pack(side='right')
        self.attachment_frame = ttk.Frame(bottom)
        self.preview = ttk.Label(self.attachment_frame)
        self.preview.pack(side='left', padx=(0, 10))
        ttk.Label(self.attachment_frame, textvariable=self.attachment, style='Muted.TLabel', wraplength=210).pack(side='left', fill='x', expand=True)
        ttk.Button(self.attachment_frame, text='Remove', command=self.remove_image).pack(side='right')
        self.entry = tk.Text(bottom, height=2, width=1, wrap='word', font=('Segoe UI', 11),
                             bg='white', fg='#243247', relief='flat', padx=12, pady=4,
                             highlightthickness=1, highlightbackground='#ccd6e1',
                             highlightcolor='#137c75', insertbackground='#137c75')
        self.entry.pack(fill='x')
        self.entry.bind('<Control-Return>', lambda _: (self.send(), 'break')[1])
        buttons = ttk.Frame(bottom)
        buttons.pack(fill='x', pady=(6, 6))
        self.send_button = ttk.Button(buttons, text='Send  ↗', style='Accent.TButton', command=self.send, width=0)
        self.send_button.pack(side='right')
        self.clear_button = ttk.Button(buttons, text='New conversation', command=self.clear)
        self.clear_button.pack(side='left')
        ttk.Button(buttons, text='Copy', command=self.copy_reply, width=0).pack(side='left', padx=6)
        self.pdf_button = ttk.Button(buttons, text='PDF Studio', command=self.open_pdf_studio, width=0, state='disabled')
        self.pdf_button.pack(side='left', padx=(0, 6))
        self.status_label = ttk.Label(bottom, textvariable=self.status, style='Muted.TLabel', wraplength=500)
        self.status_label.pack(anchor='w')
        bottom.bind('<Configure>', lambda event: self.status_label.configure(wraplength=max(160,event.width-32)))
        self.add('assistant', '## What are you working on?\nAsk a question, attach a problem, or capture part of your screen. Choose a teaching style above to learn your way.')
        self.drain_job = root.after(80, self.drain)
        self.refresh()

    def set_pdf_response(self, text):
        self.pdf_text = str(text) if text else None
        self.pdf_button.configure(state='normal' if self.pdf_text and not self.pdf_busy else 'disabled')

    def save_pdf(self):
        if self.pdf_busy or not self.pdf_text:return
        snapshot = self.pdf_text
        self.pdf_busy = True
        self.pdf_button.configure(state='disabled')
        if not self.busy:self.status.set('Preparing your PDF…')
        def ready(path, problem):
            if self.closed:return
            self.pdf_busy = False
            self.pdf_button.configure(state='normal' if self.pdf_text else 'disabled')
            if problem:
                if not self.busy:self.status.set('PDF not saved • your answer is kept for retry.')
                messagebox.showerror('Could not save PDF',problem+'\n\nYour tutor response is unchanged. You can try Save PDF again.',parent=self.root)
            else:
                self.last_pdf = path
                if not self.busy:
                    self.status.set('Saved '+path.name+' • Desktop / '+FOLDER_NAME)
        try:
            self.pdf_worker.submit(snapshot,self.pdf_folder_override,ready)
        except Exception as exc:
            ready(None,str(exc))

    def open_pdf_studio(self):
        if not self.pdf_text:return
        if self.pdf_studio and not self.pdf_studio.closed:
            self.pdf_studio.window.lift()
            self.pdf_studio.window.focus_force()
            return
        self.pdf_studio=PdfStudio(self)

    def open_graph(self):
        if self.graph_window and self.graph_window.window.winfo_exists():
            self.graph_window.window.lift()
        else:self.graph_window=GraphWindow(self.root)

    def graph_snapshot(self):
        if not self.graph_window or not self.graph_window.window.winfo_exists():
            raise ValueError('Open the graph tool and plot the functions you want, then choose Use current graph.')
        buffer=io.BytesIO()
        self.graph_window.figure.savefig(buffer,format='pdf',bbox_inches='tight',facecolor='white')
        return buffer.getvalue()

    def toggle_voice(self):
        enabled = self.voice_enabled.get()
        self.voice_toggle.configure(text='Voice on' if enabled else 'Voice off')
        self.read_button.configure(state='normal' if enabled else 'disabled')
        self.stop_voice_button.configure(state='disabled')
        if not enabled:
            self.speech.stop()
            if self.hawk_shell:self.hawk_shell.set_speech_level(0)
        self.voice_note.set('Voice ready' if enabled else 'Voice off')
        if not self.busy:self.status.set('Voice ready' if enabled else 'Voice off • local Ollama')

    def speech_event(self, state, detail):
        if not self.voice_enabled.get():return
        active = state in ('preparing', 'speaking')
        self.read_button.configure(state='disabled' if active else 'normal')
        self.stop_voice_button.configure(state='normal' if active else 'disabled')
        note = ('Voice unavailable: '+detail) if state == 'error' else detail
        self.voice_note.set(note)
        if not self.busy:self.status.set(note)

    def read_reply(self):
        if self.voice_enabled.get() and self.latest_reply:
            self.speak(self.latest_reply)

    def speak(self, text):
        if not self.voice_enabled.get():return
        self.read_button.configure(state='disabled')
        self.stop_voice_button.configure(state='normal')
        self.voice_note.set('Preparing local voice…')
        self.speech.speak(text,VOICES[self.voice_name.get()],self.voice_speed.get())

    def stop_voice(self):
        self.speech.stop()
        if self.hawk_shell:self.hawk_shell.set_speech_level(0)
        enabled=self.voice_enabled.get()
        self.read_button.configure(state='normal' if enabled else 'disabled')
        self.stop_voice_button.configure(state='disabled')
        self.voice_note.set('Voice stopped' if enabled else 'Voice off')
        if not self.busy:self.status.set('Voice stopped • local Ollama' if enabled else 'Voice off • local Ollama')

    def voice_options(self):
        if hasattr(self,'voice_window') and self.voice_window.winfo_exists():
            self.voice_window.lift();return
        window=self.voice_window=tk.Toplevel(self.root)
        window.title('Voice options — Hawkes v0.6')
        window.attributes('-topmost', self.topmost.get())
        body=ttk.Frame(window,padding=18);body.pack(fill='both',expand=True)
        ttk.Label(body,text='Offline neural voice',style='Title.TLabel').pack(anchor='w')
        ttk.Label(body,text='Voice starts off. Turn it on to read new tutor answers.',wraplength=380).pack(anchor='w',pady=8)
        ttk.Checkbutton(body,text='Voice enabled',variable=self.voice_enabled,command=self.toggle_voice).pack(anchor='w')
        ttk.Label(body,text='Voice').pack(anchor='w',pady=(12,3))
        selector=ttk.Combobox(body,textvariable=self.voice_name,values=list(VOICES),state='readonly')
        selector.pack(fill='x')
        selector.bind('<<ComboboxSelected>>',lambda event:self.stop_voice())
        ttk.Label(body,text='Speed (0.8 to 1.25)').pack(anchor='w',pady=(12,3))
        ttk.Scale(body,from_=.8,to=1.25,variable=self.voice_speed).pack(fill='x')
        row=ttk.Frame(body);row.pack(fill='x',pady=12)
        def preview():
            if not self.voice_enabled.get():
                self.voice_enabled.set(True);self.toggle_voice()
            self.speak(PREVIEW)
        ttk.Button(row,text='Preview voice',command=preview).pack(side='left')
        ttk.Button(row,text='Stop',command=self.stop_voice).pack(side='left',padx=8)
        ttk.Label(body,textvariable=self.voice_note,wraplength=380).pack(anchor='w')
        ttk.Label(body,text='Read uses the last tutor response. Complex matrices stay on screen.\nThe hawk mouth follows sound level when Hawk mode is visible.',wraplength=380).pack(anchor='w',pady=(12,0))

    def toggle_settings(self):
        self.settings_auto = False
        self.show_settings(not self.settings_visible)

    def show_settings(self, visible):
        self.settings_visible = visible
        if visible:
            self.settings_panel.grid()
        else:
            self.settings_panel.grid_remove()
        if hasattr(self, 'settings_button'):
            self.settings_button.configure(text='Settings ▴' if visible else 'Settings ▾')

    def adapt_settings(self, event):
        if event.widget is self.surface and self.settings_auto:
            self.show_settings(event.height >= 640)

    def configure_theme(self):
        self.root.configure(bg='#f3f6fa')
        theme = ttk.Style(self.root)
        theme.theme_use('clam')
        theme.configure('.', font=('Segoe UI', 10), background='#f3f6fa', foreground='#243247')
        theme.configure('TFrame', background='#f3f6fa')
        theme.configure('Card.TFrame', background='#dce3eb')
        theme.configure('Title.TLabel', font=('Segoe UI', 17, 'bold'), foreground='#172b43')
        theme.configure('Muted.TLabel', foreground='#607086', font=('Segoe UI', 9))
        theme.configure('TButton', padding=(8, 4), background='#e5ebf2', borderwidth=0)
        theme.map('TButton', background=[('active', '#d6e2ed')])
        theme.configure('Accent.TButton', background='#137c75', foreground='white', font=('Segoe UI', 10, 'bold'))
        theme.map('Accent.TButton', background=[('disabled', '#a7b7be'), ('active', '#0d655f')])
        theme.configure('TCombobox', padding=6, fieldbackground='white')
        theme.map('TCombobox', fieldbackground=[('readonly', 'white')])
        theme.configure('TCheckbutton', background='#f3f6fa')
        # Nine-slice image borders keep standard ttk keyboard/focus behavior.
        self.button_skins = []
        for prefix, colors in [('Soft', ('#e6edf4','#d8e7ee','#cbdfe5','#e9edf1')),
                               ('Accent', ('#137c75','#0d6b65','#095a55','#a7b7be'))]:
            skins = []
            for color in colors:
                tile = Image.new('RGBA', (72,72), (0,0,0,0))
                ImageDraw.Draw(tile).rounded_rectangle((0,0,71,71), radius=24, fill=color)
                photo = ImageTk.PhotoImage(tile.resize((36,36), Image.Resampling.LANCZOS),master=self.root)
                self.button_skins.append(photo)
                skins.append(photo)
            element = prefix + '.rounded'
            theme.element_create(element, 'image', skins[0],
                ('disabled',skins[3]), ('pressed',skins[2]), ('active',skins[1]),
                border=6, sticky='nsew')
            name = 'TButton' if prefix == 'Soft' else 'Accent.TButton'
            theme.layout(name, [(element, {'sticky':'nsew', 'children':[
                ('Button.focus', {'sticky':'nsew','children':[
                    ('Button.padding', {'sticky':'nsew','children':[
                        ('Button.label', {'sticky':'nsew'})]})]})]})])


    def update_horizontal(self, first, last):
        self.horizontal.set(first, last)
        if float(first) > 0.001 or float(last) < 0.999:
            if not self.horizontal.winfo_manager():
                self.horizontal.pack(fill='x', side='bottom')
        else:
            self.horizontal.pack_forget()

    def schedule_reflow(self, event=None):
        if self.resize_job:
            self.root.after_cancel(self.resize_job)
        self.resize_job = self.root.after(250, self.reflow)

    def reflow(self):
        self.resize_job = None
        width = max(280, self.chat.winfo_width() - 38)
        for record in self.rendered_messages:
            if abs(record['width'] - width) > 24:
                record['width'] = width
                record['revision'] += 1
                self.render_message(record, follow=False)

    def render_message(self, record, follow):
        generation, revision = self.generation, record['revision']
        initial_view = self.chat.yview()
        def ready(images, errors, failure):
            if generation != self.generation or revision != record['revision']:
                return
            should_follow = follow and self.chat.yview() == initial_view
            visible = self.chat.index('@0,0')
            self.chat.mark_set('keep_view', visible)
            self.chat.configure(state='normal')
            self.chat.delete(record['start'], record['end'])
            self.chat.mark_gravity(record['end'], 'right')
            photos = []
            if failure:
                self.chat.insert(record['start'], record['text'] + '\n[Formatting unavailable: ' + failure + ']')
            else:
                for rendered in reversed(images):
                    photo = ImageTk.PhotoImage(rendered,master=self.root)
                    photos.append(photo)
                    self.chat.insert(record['start'], '\n')
                    self.chat.image_create(record['start'], image=photo)
            self.chat.mark_gravity(record['end'], 'left')
            record['photos'] = photos
            self.photos = [photo for item in self.rendered_messages for photo in item.get('photos', [])] + self.attachment_photos
            self.chat.configure(state='disabled')
            if should_follow:
                self.chat.yview(record['heading'])
            elif not follow:
                self.chat.yview('keep_view')
        self.renderer.submit(record['text'], record['width'], ready)

    def drain(self):
        try:
            while True:
                fn = self.jobs.get_nowait()
                fn()
        except queue.Empty:
            pass
        if self.hawk_shell:
            self.hawk_shell.set_speech_level(self.speech.level if self.voice_enabled.get() else 0)
        self.drain_job = self.root.after(80, self.drain)

    def api(self, endpoint, payload=None):
        data = None if payload is None else json.dumps(payload).encode('utf-8')
        req = request.Request(URL + endpoint, data=data, headers={'Content-Type': 'application/json'})
        # Bypass OS proxy settings for the fixed loopback service.
        with request.build_opener(request.ProxyHandler({})).open(req, timeout=300) as res:
            return json.load(res)

    def refresh(self):
        def worker():
            try:
                models = [m['name'] for m in self.api('/tags').get('models', [])]
                def done():
                    self.models['values'] = models
                    if models and self.model.get() not in models:
                        self.model.set(('qwen3:8b' if 'qwen3:8b' in models else next((m for m in models if 'qwen' in m.lower() and 'vl' not in m.lower()), models[0])))
                    if not self.busy:
                        self.status.set(f'Ollama connected • {len(models)} model(s)' + ('' if VISION_MODEL in models else ' • For images: ollama pull qwen3-vl:8b'))
                self.jobs.put(done)
            except Exception:
                self.jobs.put(lambda: self.status.set('Cannot connect — start Ollama, then Refresh models.'))
        threading.Thread(target=worker, daemon=True).start()

    def add(self, who, msg, image_data=None):
        self.chat.configure(state='normal')
        self.render_id += 1
        heading = 'heading_' + str(self.render_id)
        self.chat.mark_set(heading, 'end-1c')
        self.chat.mark_gravity(heading, 'left')
        self.chat.insert('end', 'YOU\n' if who == 'user' else 'HAWKES TUTOR\n', who)
        if who == 'assistant':
            self.latest_reply = msg
            mark = 'render_' + str(self.render_id)
            self.chat.mark_set(mark, 'end-1c')
            self.chat.mark_gravity(mark, 'left')
            self.chat.insert('end', 'Formatting response locally…')
            endmark = mark + '_end'
            self.chat.mark_set(endmark, 'end-1c')
            self.chat.mark_gravity(endmark, 'left')
            record = dict(start=mark, end=endmark, heading=heading, text=msg,
                          width=max(280, self.chat.winfo_width()-38), revision=0, photos=[])
            self.rendered_messages.append(record)
        else:
            self.chat.insert('end', msg)
        if image_data:
            image = Image.open(io.BytesIO(base64.b64decode(image_data)))
            image.thumbnail((280, 150))
            photo = ImageTk.PhotoImage(image,master=self.root)
            self.attachment_photos.append(photo)
            self.photos.append(photo)
            self.chat.insert('end', '\n')
            self.chat.image_create('end', image=photo)
        self.chat.insert('end', '\n\n')
        self.chat.configure(state='disabled')
        self.chat.yview(heading)
        if who == 'assistant':
            self.render_message(record, follow=True)

    def copy_reply(self):
        if self.latest_reply:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.latest_reply)

    def close(self):
        if self.closed:return
        self.closed=True
        self.root.after_cancel(self.drain_job)
        if self.resize_job:
            self.root.after_cancel(self.resize_job)
        self.speech.close()
        if self.pdf_studio and not self.pdf_studio.closed:self.pdf_studio.close()
        self.pdf_worker.close()
        self.renderer.close()
        # Release Tk-owned images and queued closures on the UI thread.
        while not self.jobs.empty():
            try: self.jobs.get_nowait()
            except queue.Empty: break
        self.photos.clear()
        self.attachment_photos.clear()
        self.rendered_messages.clear()
        self.button_skins.clear()
        self.chat_panel.surface_photo = None
        self.preview_photo = None
        self.root.destroy()
        for name in ('model','style','status','attachment','topmost','voice_enabled','voice_name','voice_speed','voice_note'):
            setattr(self, name, None)
        import gc
        gc.collect()

    def set_image(self, image, name):
        self.pending = encode_image(image)
        thumbnail = image.copy()
        thumbnail.thumbnail((96, 52))
        self.preview_photo = ImageTk.PhotoImage(thumbnail,master=self.root)
        self.preview.configure(image=self.preview_photo)
        self.attachment_frame.pack(fill='x', pady=(0, 8), before=self.entry)
        self.attachment.set(name + ' • will use qwen3-vl:8b')

    def attach(self):
        path = filedialog.askopenfilename(filetypes=[('Images', '*.png *.jpg *.jpeg *.webp *.bmp'), ('All files', '*.*')])
        if path:
            try:
                with Image.open(path) as image:
                    self.set_image(ImageOps.exif_transpose(image), 'Attached image')
            except Exception as exc:
                messagebox.showerror('Cannot open image', str(exc))

    def remove_image(self):
        self.pending = None
        self.attachment_frame.pack_forget()
        self.preview.configure(image='')
        self.preview_photo = None
        self.attachment.set('No image attached')

    def capture(self):
        self.root.withdraw()
        self.root.after(300, self.begin_capture)

    def begin_capture(self):
        try:
            # One frozen full-desktop frame avoids overlay contamination and supports negative monitor origins.
            import ctypes
            user32 = ctypes.windll.user32
            left, top = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
            shot = ImageGrab.grab(all_screens=True)
            overlay = tk.Toplevel(self.root)
            overlay.overrideredirect(True)
            overlay.attributes('-topmost', True)
            overlay.geometry(f'{shot.width}x{shot.height}+0+0')
            overlay.update_idletasks()
            # Tk treats negative geometry coordinates as right/bottom offsets;
            # place the native window explicitly for monitors left of the primary.
            hwnd = user32.GetParent(overlay.winfo_id()) or overlay.winfo_id()
            user32.SetWindowPos(hwnd, -1, left, top, shot.width, shot.height, 0x0040)
            canvas = tk.Canvas(overlay, highlightthickness=0, cursor='crosshair')
            canvas.pack(fill='both', expand=True)
            overlay.photo = ImageTk.PhotoImage(shot,master=self.root)
            canvas.create_image(0, 0, image=overlay.photo, anchor='nw')
            canvas.create_text(20, 20, anchor='nw', text='Drag a rectangle to capture • Esc cancels', fill='#ffffff', font=('Segoe UI', 16, 'bold'))
            start, rectangle = [], []
            def close():
                overlay.destroy()
                self.root.deiconify()
            def press(event):
                start[:] = [event.x, event.y]
                if rectangle: canvas.delete(rectangle.pop())
                rectangle.append(canvas.create_rectangle(event.x, event.y, event.x, event.y, outline='#00bfff', width=3))
            def drag(event):
                if start: canvas.coords(rectangle[0], *start, event.x, event.y)
            def release(event):
                if not start: return
                x1, x2 = sorted((max(0, min(shot.width, start[0])), max(0, min(shot.width, event.x))))
                y1, y2 = sorted((max(0, min(shot.height, start[1])), max(0, min(shot.height, event.y))))
                close()
                if x2 - x1 >= 8 and y2 - y1 >= 8:
                    self.set_image(shot.crop((x1, y1, x2, y2)), 'Screen region')
            canvas.bind('<ButtonPress-1>', press)
            canvas.bind('<B1-Motion>', drag)
            canvas.bind('<ButtonRelease-1>', release)
            overlay.bind('<Escape>', lambda _: close())
            overlay.focus_force()
        except Exception as exc:
            self.root.deiconify()
            messagebox.showerror('Capture failed', str(exc) + '\nYou can also attach an image saved with Windows Snipping Tool.')

    def clear(self):
        if self.busy: return
        self.stop_voice()
        self.set_pdf_response(None)
        self.generation += 1
        self.latest_reply = ""
        self.history.clear()
        self.photos.clear()
        self.attachment_photos.clear()
        self.rendered_messages.clear()
        self.remove_image()
        self.chat.configure(state='normal')
        self.chat.delete('1.0', 'end')
        self.chat.configure(state='disabled')
        self.add('assistant', 'New conversation started. What would you like to work on?')

    def send(self):
        if self.busy: return
        msg = self.entry.get('1.0', 'end').strip()
        image = self.pending
        if not msg and not image: return
        # Preserve vision context on follow-ups, even when the text selector is a text-only model.
        has_images = bool(image) or any(m.get('images') for m in self.history)
        model = VISION_MODEL if has_images else self.model.get().strip()
        if not model:
            messagebox.showwarning('Choose a model', 'Start Ollama and refresh the model list.')
            return
        msg = msg or 'Help me understand the mathematics in this image.'
        user = {'role': 'user', 'content': msg}
        if image: user['images'] = [image]
        messages = [{'role': 'system', 'content': SYSTEM + STYLES[self.style.get()]}] + list(self.history) + [user]
        self.busy = True
        self.send_button.configure(state='disabled')
        self.clear_button.configure(state='disabled')
        self.stop_voice()
        self.status.set(f'{model} is thinking locally...')
        # Keep the draft and attachment intact until the request succeeds, for easy retry.
        def worker():
            try:
                reply = self.api('/chat', {'model': model, 'messages': messages, 'stream': False, 'options': {'temperature': .5}})['message']['content']
                if not reply.strip(): raise ValueError('The model returned an empty response. Try again.')
                def done():
                    self.history.extend([user, {'role': 'assistant', 'content': reply}])
                    self.add('user', msg, image)
                    self.add('assistant', reply)
                    self.set_pdf_response(reply)
                    if self.entry.get('1.0', 'end').strip() == msg or (image and not self.entry.get('1.0', 'end').strip()):
                        self.entry.delete('1.0', 'end')
                    if self.pending == image: self.remove_image()
                    self.finish('Ready • local Ollama • ' + model)
                    if self.voice_enabled.get():self.speak(reply)
                self.jobs.put(done)
            except Exception as exc:
                problem = str(exc)
                def fail():
                    self.finish('Request failed • your question and image are kept for retry.')
                    messagebox.showerror('Ollama request failed', problem + '\n\nStart Ollama. For images, install the model with:\nollama pull qwen3-vl:8b\n\nThen retry. Large images/models can take several minutes.')
                self.jobs.put(fail)
        threading.Thread(target=worker, daemon=True).start()

    def finish(self, status):
        self.busy = False
        self.send_button.configure(state='normal')
        self.clear_button.configure(state='normal')
        self.status.set(status)


if __name__ == '__main__':
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    import sys
    root = tk.Tk()
    from hawk_shell import HawkShell
    shell = HawkShell(root, start_mode='hawk' if '--hawk' in sys.argv else 'compact')
    app = Companion(root, surface=shell.content)
    app.hawk_shell = shell
    shell.on_close = app.close
    shell.start()
    root.mainloop()
