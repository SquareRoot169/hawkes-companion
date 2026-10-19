"""PDF Studio: controlled templates and an actual compiled-page preview."""
from dataclasses import replace
from datetime import datetime
import os
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import ImageTk
import pypdfium2 as pdfium

from hawkes_latex import (PdfOptions, LatexWorker, TEMPLATES, ACCENTS, save_latex_source,
                         load_options, save_options, save_document)
from hawkes_pdf import export_directory

class PdfStudio:
    def __init__(self,app):
        self.app=app;self.text=app.pdf_text;self.closed=False;self.busy=False
        self.data=None;self.document=None;self.photo=None;self.page=0;self.compiled_options=None
        self.graph_data=None;self.revision=0;self.auto_save=False;self.pending_redraw=None
        self.compiled_revision=-1;self.refresh_job=None;self.initial_job=None
        self.save_requested=False
        self.fields={};self.choices={}
        self.worker=LatexWorker(app.jobs)
        self.window=tk.Toplevel(app.root);self.window.title('PDF Studio — Hawkes Companion v0.7')
        self.window.attributes('-topmost',app.root.attributes('-topmost'))
        sw,sh=self.window.winfo_screenwidth(),self.window.winfo_screenheight()
        self.window.geometry(f'{min(1020,sw-60)}x{min(780,sh-90)}')
        self.window.minsize(min(760,sw-60),min(600,sh-90))
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        self.window.columnconfigure(1,weight=1);self.window.rowconfigure(1,weight=1)
        top=ttk.Frame(self.window,padding=(16,12));top.grid(row=0,column=0,columnspan=2,sticky='ew')
        ttk.Label(top,text='PDF Studio',style='Title.TLabel').pack(side='left')
        ttk.Label(top,text='LaTeX typesetting · Latest answer at opening',style='Muted.TLabel').pack(side='right')
        controls=ttk.Frame(self.window,padding=(12,0,12,6));controls.grid(row=1,column=0,sticky='ns')
        notebook=self.notebook=ttk.Notebook(controls);notebook.pack(fill='both',expand=True)
        options=load_options()
        self.vars={}
        for key,value in options.__dict__.items():
            self.vars[key]=(tk.BooleanVar(value=value) if isinstance(value,bool) else tk.StringVar(value=str(value)))
        if options.filename=='Hawkes Notes':
            self.vars['filename'].set('Notes '+datetime.now().strftime('%Y-%m-%d %H-%M'))
        # Metadata is independent of answer content; equations in headings stay intact.
        for title in ('Document','Appearance','Graphs'):
            frame=ttk.Frame(notebook,padding=12);notebook.add(frame,text=title)
            setattr(self,title.lower()+'_tab',frame)
        self.field(self.document_tab,'Document title','title')
        self.field(self.document_tab,'Your name (optional)','author')
        self.field(self.document_tab,'Date (leave blank to hide)','date')
        self.field(self.document_tab,'Filename','filename')
        ttk.Label(self.document_tab,text='Saves automatically to\nDesktop / Hawkes Companion PDFs\n\nExports the answer that was present\nwhen this window opened.\n\nChat appearance stays the same.',wraplength=245,style='Muted.TLabel').pack(anchor='w',pady=12)
        for label,key,values in [('Template','template',TEMPLATES),('Text size','size',('10','11','12')),
               ('Margins','margins',('Standard','Generous','Compact')),('Paper','paper',('Letter','A4')),
               ('Heading color','accent',tuple(ACCENTS))]:self.choice(self.appearance_tab,label,key,values)
        self.number_check=ttk.Checkbutton(self.appearance_tab,text='Number displayed equations',variable=self.vars['numbers'])
        self.number_check.pack(anchor='w',pady=(8,3))
        self.page_check=ttk.Checkbutton(self.appearance_tab,text='Show page numbers',variable=self.vars['pages'])
        self.page_check.pack(anchor='w',pady=3)
        ttk.Label(self.appearance_tab,text='Uses traditional Latin Modern fonts\nand standard LaTeX mathematics.\nExisting boxed answers are preserved.',wraplength=245,style='Muted.TLabel').pack(anchor='w',pady=12)
        self.graph_check=ttk.Checkbutton(self.graphs_tab,text='Include a graph',variable=self.vars['graphs'])
        self.graph_check.pack(anchor='w',pady=(0,8))
        ttk.Button(self.graphs_tab,text='Open graph tool',command=self.open_graph).pack(fill='x',pady=4)
        self.graph_button=ttk.Button(self.graphs_tab,text='Use current graph',command=self.capture_graph)
        self.graph_button.pack(fill='x',pady=4)
        self.graph_note=tk.StringVar(value='No graph selected.')
        ttk.Label(self.graphs_tab,textvariable=self.graph_note,wraplength=245,style='Muted.TLabel').pack(anchor='w',pady=8)
        self.field(self.graphs_tab,'Graph caption','caption')
        ttk.Label(self.graphs_tab,text='Plot your functions, then choose\nUse current graph. The PDF includes\na sharp vector copy of that graph.\n\nThe selection is a snapshot; choose\nit again after changing the plot.',wraplength=245,style='Muted.TLabel').pack(anchor='w',pady=12)
        self.vars['graphs'].set(False)
        preview=ttk.Frame(self.window,padding=(0,0,12,6));preview.grid(row=1,column=1,sticky='nsew')
        preview.columnconfigure(0,weight=1);preview.rowconfigure(1,weight=1)
        toolbar=ttk.Frame(preview);toolbar.grid(row=0,column=0,sticky='ew',pady=(0,6))
        self.previous_button=ttk.Button(toolbar,text='‹',width=3,command=lambda:self.turn(-1))
        self.previous_button.pack(side='left')
        self.page_label=tk.StringVar(value='No preview yet')
        ttk.Label(toolbar,textvariable=self.page_label).pack(side='left',padx=8)
        self.next_button=ttk.Button(toolbar,text='›',width=3,command=lambda:self.turn(1))
        self.next_button.pack(side='left')
        ttk.Label(toolbar,text='Zoom').pack(side='left',padx=(14,4))
        self.zoom=tk.StringVar(value='Fit width')
        zoom=self.zoom_choice=ttk.Combobox(toolbar,textvariable=self.zoom,values=('Fit width','75%','100%','125%'),state='readonly',width=9)
        zoom.pack(side='left');zoom.bind('<<ComboboxSelected>>',lambda _:self.redraw())
        self.canvas=tk.Canvas(preview,bg='#dce2e8',highlightthickness=0)
        self.canvas.grid(row=1,column=0,sticky='nsew')
        ys=ttk.Scrollbar(preview,orient='vertical',command=self.canvas.yview);ys.grid(row=1,column=1,sticky='ns')
        xs=ttk.Scrollbar(preview,orient='horizontal',command=self.canvas.xview);xs.grid(row=2,column=0,sticky='ew')
        self.canvas.configure(yscrollcommand=ys.set,xscrollcommand=xs.set)
        self.canvas.bind('<Configure>',self.resize_preview)
        self.canvas.bind('<MouseWheel>',lambda e:self.canvas.yview_scroll(-int(e.delta/120),'units'))
        bottom=ttk.Frame(self.window,padding=(14,8,14,12));bottom.grid(row=2,column=0,columnspan=2,sticky='ew')
        self.note=tk.StringVar(value='Preparing preview…')
        self.note_label=ttk.Label(bottom,textvariable=self.note,wraplength=650,style='Muted.TLabel')
        self.note_label.pack(anchor='w',pady=(0,8))
        bottom.bind('<Configure>',lambda event:self.note_label.configure(wraplength=max(250,event.width-32)))
        row=ttk.Frame(bottom);row.pack(fill='x')
        self.preview_button=ttk.Button(row,text='Update preview',command=self.generate);self.preview_button.pack(side='left')
        ttk.Button(row,text='Open PDF folder',command=self.open_folder).pack(side='left',padx=8)
        self.save_button=ttk.Button(row,text='Save PDF',style='Accent.TButton',command=self.save);self.save_button.pack(side='right')
        ttk.Button(row,text='Close',command=self.close).pack(side='right',padx=8)
        source_row=ttk.Frame(bottom);source_row.pack(fill='x',pady=(6,0))
        self.latex_button=ttk.Button(source_row,text='Save LaTeX',command=self.save_source)
        self.latex_button.pack(side='left')
        ttk.Label(source_row,text='Complete .tex document + selected graph',style='Muted.TLabel').pack(side='left',padx=8)
        for key,var in self.vars.items():var.trace_add('write',lambda *_,key=key:self.changed(key))
        self.initial_job=self.window.after(100,self.initial_preview)

    def field(self,parent,label,key):
        ttk.Label(parent,text=label).pack(anchor='w',pady=(6,3))
        self.fields[key]=ttk.Entry(parent,textvariable=self.vars[key],width=29)
        self.fields[key].pack(fill='x',pady=(0,5))
    def choice(self,parent,label,key,values):
        ttk.Label(parent,text=label).pack(anchor='w',pady=(5,2))
        self.choices[key]=ttk.Combobox(parent,textvariable=self.vars[key],values=values,state='readonly',width=27)
        self.choices[key].pack(fill='x',pady=(0,4))
    def options(self):
        values={key:var.get() for key,var in self.vars.items()};values['size']=int(values['size'])
        return PdfOptions(**values).validate()
    def initial_preview(self):
        self.initial_job=None
        self.generate(interactive=False)
    def changed(self,key=None,*_):
        if self.closed:return
        if key=='filename':
            if not self.busy:self.note.set('Filename updated. Save PDF will use this name.')
            return
        if key=='graphs' and self.vars['graphs'].get() and not self.graph_data:
            try:
                self.graph_data=self.app.graph_snapshot()
                self.graph_note.set('Current graph selected for export.')
            except Exception:
                self.graph_note.set('Open the graph tool, plot your functions, then choose Use current graph.')
        self.revision+=1
        self.note.set('Updating preview with your latest settings…')
        if self.refresh_job:self.window.after_cancel(self.refresh_job)
        self.refresh_job=self.window.after(450,self.refresh_preview)
    def refresh_preview(self):
        self.refresh_job=None
        if not self.closed and not self.busy:self.generate(interactive=False)
    def open_graph(self):
        self.app.open_graph()
        graph=self.app.graph_window.window
        # Keep the plot accessible above a topmost PDF Studio, and return to
        # this same studio when the graph is closed.
        graph.transient(self.window)
        graph.lift();graph.focus_set()
    def capture_graph(self):
        try:self.graph_data=self.app.graph_snapshot()
        except Exception as exc:messagebox.showinfo('Choose a graph',str(exc),parent=self.window);return
        self.vars['graphs'].set(True);self.graph_note.set('Current graph selected for export.');self.changed()
    def generate(self,save_after=False,interactive=True):
        if self.closed:return
        if save_after:self.save_requested=True
        if self.busy:return
        if self.refresh_job:self.window.after_cancel(self.refresh_job);self.refresh_job=None
        try:
            options=self.options()
            if options.graphs and not self.graph_data:raise ValueError('Choose Use current graph in the Graphs tab first.')
        except Exception as exc:
            self.save_requested=False;self.note.set(str(exc))
            if interactive:messagebox.showerror('Check PDF settings',str(exc),parent=self.window)
            return
        self.auto_save=save_after;self.busy=True;revision=self.revision
        self.preview_button.configure(state='disabled')
        self.note.set('Typesetting with LaTeX… Changes and Save requests will use the latest settings.')
        def ready(data,error):
            if self.closed:return
            self.busy=False;self.preview_button.configure(state='normal');self.save_button.configure(state='normal')
            if revision!=self.revision:
                # Never display or save an obsolete render after the user
                # changes settings while the compiler is still running.
                self.generate(interactive=False)
                return
            if error:
                self.save_requested=False
                self.note.set('Preview not updated: '+error)
                if interactive:messagebox.showerror('Could not typeset PDF',error,parent=self.window)
                return
            try:
                doc=pdfium.PdfDocument(data)
                if self.document:self.document.close()
                self.document=doc;self.data=data;self.compiled_options=options;self.compiled_revision=revision;self.page=0
                self.redraw();save_options(self.options())
                self.note.set('Preview is up to date. Save PDF stores these exact pages.')
                if self.save_requested:self.save_requested=False;self.commit()
            except Exception as exc:
                self.save_requested=False
                self.note.set('Preview unavailable; no PDF saved.')
                messagebox.showerror('Preview unavailable',str(exc),parent=self.window)
        try:self.worker.submit(self.text,options,self.graph_data,ready)
        except Exception as exc:ready(None,str(exc))
    def save(self):
        if self.closed:return
        if self.busy:
            self.save_requested=True
            self.note.set('Save requested. Finishing the preview with your latest settings…')
            return
        if self.data is None or self.compiled_revision!=self.revision:self.generate(save_after=True)
        else:self.commit()
    def commit(self):
        try:
            options=replace(self.compiled_options,filename=self.vars['filename'].get())
            path=save_document(self.data,options,self.app.pdf_folder_override)
            save_options(options)
            self.app.last_pdf=path;self.note.set('Saved '+path.name+' · Desktop / Hawkes Companion PDFs')
            if not self.app.busy:self.app.status.set('PDF saved · '+path.name)
        except Exception as exc:messagebox.showerror('Could not save PDF',str(exc),parent=self.window)
    def save_source(self):
        if self.closed:return
        try:
            # Snapshot the visible settings, even while a preview is compiling.
            # No separate AI call or conversion of the PDF back to text occurs.
            options=self.options()
            path=save_latex_source(self.text,options,self.graph_data,self.app.pdf_folder_override)
            save_options(options)
            self.last_latex=path
            self.note.set('LaTeX saved · '+path.parent.name+' / main.tex · Desktop / Hawkes Companion PDFs')
            if not self.app.busy:self.app.status.set('LaTeX source saved · '+path.parent.name)
        except Exception as exc:messagebox.showerror('Could not save LaTeX',str(exc),parent=self.window)
    def redraw(self):
        if self.closed or not self.document:return
        page=self.document[self.page]
        try:
            width,height=page.get_size()
            scale=max(.2,min(2.2,(self.canvas.winfo_width()-30)/width)) if self.zoom.get()=='Fit width' else int(self.zoom.get().strip('%'))/100
            bitmap=page.render(scale=scale)
            try:image=bitmap.to_pil().copy()
            finally:bitmap.close()
        finally:page.close()
        self.photo=ImageTk.PhotoImage(image,master=self.window)
        self.canvas.delete('all');self.canvas.create_image(15,15,image=self.photo,anchor='nw')
        self.canvas.configure(scrollregion=(0,0,image.width+30,image.height+30));self.canvas.yview_moveto(0)
        self.page_label.set(f'Page {self.page+1} of {len(self.document)}')
        self.previous_button.configure(state='normal' if self.page>0 else 'disabled')
        self.next_button.configure(state='normal' if self.page+1<len(self.document) else 'disabled')
    def resize_preview(self,event=None):
        if self.pending_redraw:self.window.after_cancel(self.pending_redraw)
        self.pending_redraw=self.window.after(180,self.delayed_redraw)
    def delayed_redraw(self):self.pending_redraw=None;self.redraw()
    def turn(self,delta):
        if self.document:self.page=max(0,min(len(self.document)-1,self.page+delta));self.redraw()
    def open_folder(self):
        try:
            folder=self.app.pdf_folder_override or export_directory();folder.mkdir(parents=True,exist_ok=True);os.startfile(str(folder))
        except Exception as exc:messagebox.showerror('Could not open folder',str(exc),parent=self.window)
    def close(self):
        if self.closed:return
        self.closed=True;self.worker.close()
        if self.refresh_job:self.window.after_cancel(self.refresh_job)
        if self.initial_job:self.window.after_cancel(self.initial_job)
        if self.pending_redraw:self.window.after_cancel(self.pending_redraw)
        if self.document:self.document.close();self.document=None
        self.window.destroy()
