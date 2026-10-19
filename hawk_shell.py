"""Offline hawk-shaped window. The existing tutor widgets live in its center."""
from pathlib import Path
import tkinter as tk
from PIL import Image, ImageTk

BASE = Path(__file__).resolve().parent
KEY = '#010203'


def screen_bounds(width, height):
    """Content stays below the hawk's face and above its talons."""
    left, top = round(width*.19), round(height*.23)
    return left, top, round(width*.62), round(height*.65)


class HawkShell:
    def __init__(self, root, start_mode='hawk'):
        self.root = root
        self.on_close = root.destroy
        self.mode = start_mode
        self.last_size = None
        self.paint_job = None
        self.restore_job = None
        self.minimized = False
        self.fit = False
        self.saved_geometry = None
        self.drag_origin = None
        self.resize_origin = None
        self.hawk_geometry = None
        self.compact_geometry = None
        with Image.open(BASE / 'assets' / 'hawk.png') as image:
            self.art = image.convert('RGBA')
        with Image.open(BASE / 'assets' / 'hawk_open.png') as image:
            self.open_art = image.convert('RGBA').resize(self.art.size,Image.Resampling.LANCZOS)
        self.mouth_open = False
        self.mouth_photo = None
        self.canvas = tk.Canvas(root, bg=KEY, highlightthickness=0, borderwidth=0)
        self.canvas.place(x=0,y=0,relwidth=1,relheight=1)
        self.art_item = self.canvas.create_image(0,0,anchor='nw')
        self.mouth_item = self.canvas.create_image(0,0,anchor='nw',state='hidden')
        self.content = tk.Frame(root, bg='#f3f6fa', highlightthickness=1,
                                highlightbackground='#b78a4b')
        self.bar = tk.Frame(root, bg='#193c3a', padx=4, pady=3)
        self.bar_buttons = []
        for label, action in [('Screen mode',self.toggle_mode),('−',self.minimize),
                              ('□',self.toggle_fit),('×',self.close)]:
            button = tk.Button(self.bar, text=label, command=action,
                 bg='#193c3a', fg='#fff4d9', activebackground='#34635d',
                 activeforeground='white', relief='flat', borderwidth=0,
                 font=('Segoe UI',10), padx=8, pady=2, takefocus=True)
            button.pack(side='left')
            self.bar_buttons.append(button)
        self.grip = tk.Label(root, text='◢', bg='#193c3a', fg='#f0c77e',
                             font=('Segoe UI',14), cursor='size_nw_se', padx=5)
        self.canvas.bind('<ButtonPress-1>',self.begin_move)
        self.canvas.bind('<B1-Motion>',self.move)
        self.grip.bind('<ButtonPress-1>',self.begin_resize)
        self.grip.bind('<B1-Motion>',self.resize)
        self.root.bind('<Configure>',self.schedule_paint, add='+')
        self.root.bind('<Map>',self.restore,add='+')
        self.root.bind('<F10>',lambda event:(self.toggle_mode(),'break')[1],add='+')
        self.root.bind('<Escape>',self.exit_expanded,add='+')
        self.root.bind('<Alt-F4>',lambda event:self.close(),add='+')
        self.root.bind('<Destroy>',self.destroyed,add='+')

    def start(self):
        self.root.update_idletasks()
        w=min(1040,max(720,self.root.winfo_screenwidth()-60))
        h=min(980,max(560,self.root.winfo_screenheight()-90))
        x=max(0,(self.root.winfo_screenwidth()-w)//2)
        y=max(0,(self.root.winfo_screenheight()-h)//2-20)
        self.hawk_geometry=f'{w}x{h}+{x}+{y}'
        if self.mode == 'compact':
            self.compact_geometry=f'700x{min(800,self.root.winfo_screenheight()-90)}+{x}+{y}'
            self.root.geometry(self.compact_geometry)
        else:
            self.root.geometry(self.hawk_geometry)
        self.apply_mode()
        self.root.after_idle(self.paint)

    def apply_mode(self):
        if self.mode=='hawk':
            self.root.minsize(min(920,self.root.winfo_screenwidth()-60),
                              min(780,self.root.winfo_screenheight()-90))
            self.root.configure(bg=KEY)
            self.root.attributes('-transparentcolor',KEY)
            self.root.overrideredirect(True)
            self.canvas.place(x=0,y=0,relwidth=1,relheight=1)
            self.grip.place(relx=.81,rely=.88,anchor='ne')
            self.bar_buttons[0].configure(text='Screen mode')
        else:
            self.root.overrideredirect(False)
            self.root.attributes('-transparentcolor','')
            self.root.configure(bg='#f3f6fa')
            self.root.minsize(min(560,self.root.winfo_screenwidth()-60),
                              min(600,self.root.winfo_screenheight()-90))
            self.canvas.place_forget()
            self.grip.place_forget()
            self.bar_buttons[0].configure(text='Hawk mode')
        self.paint()

    def schedule_paint(self,event):
        if event.widget is not self.root:return
        self.layout_content()
        if self.paint_job:self.root.after_cancel(self.paint_job)
        self.paint_job=self.root.after(90,self.paint)

    def layout_content(self):
        w,h=self.root.winfo_width(),self.root.winfo_height()
        if self.mode=='hawk':
            x,y,cw,ch=screen_bounds(w,h)
            self.content.place(x=x,y=y,anchor='nw',relwidth=0,relheight=0,width=cw,height=ch)
            self.bar.place(x=x+cw,y=y-2,anchor='se',relwidth=0,relheight=0,
                           width=self.bar.winfo_reqwidth(),height=self.bar.winfo_reqheight())
            self.grip.place(x=x+cw,y=y+ch+2,anchor='ne')
        else:
            self.bar.place(x=0,y=0,anchor='nw',relwidth=1,relheight=0,
                           width=0,height=self.bar.winfo_reqheight())
            self.content.place(x=0,y=self.bar.winfo_reqheight(),anchor='nw',relwidth=1,
                               relheight=1,width=0,height=-self.bar.winfo_reqheight())
        self.content.lift()
        self.bar.lift()
        if self.mode=='hawk':self.grip.lift()

    def paint(self):
        self.paint_job=None
        if not self.root.winfo_exists():return
        self.layout_content()
        if self.mode!='hawk':return
        w,h=max(1,self.root.winfo_width()),max(1,self.root.winfo_height())
        # Runtime scaling/compositing only; the original artwork stays intact.
        if self.last_size == (w,h):return
        self.last_size=(w,h)
        scaled=self.art.resize((w,h),Image.Resampling.LANCZOS)
        background=Image.new('RGBA',(w,h),KEY)
        background.alpha_composite(scaled)
        self.photo=ImageTk.PhotoImage(background.convert('RGB'),master=self.root)
        self.canvas.itemconfigure(self.art_item,image=self.photo)
        aw,ah=self.open_art.size
        # The generated open frame supplies only the beak patch; eyes, wings,
        # feathers and the rest of the original never flicker between frames.
        patch=self.open_art.crop((round(aw*.44),round(ah*.095),round(aw*.56),round(ah*.175)))
        patch=patch.resize((max(1,round(w*.12)),max(1,round(h*.08))),Image.Resampling.LANCZOS)
        self.mouth_photo=ImageTk.PhotoImage(patch,master=self.root)
        self.canvas.coords(self.mouth_item,round(w*.44),round(h*.095))
        self.canvas.itemconfigure(self.mouth_item,image=self.mouth_photo,
                                 state='normal' if self.mouth_open else 'hidden')

    def set_speech_level(self,level):
        opened = level > (.055 if self.mouth_open else .10)
        if opened != self.mouth_open:
            self.mouth_open=opened
            self.canvas.itemconfigure(self.mouth_item,state='normal' if opened else 'hidden')

    def begin_move(self,event):
        self.drag_origin=(event.x_root,event.y_root,self.root.winfo_x(),self.root.winfo_y())

    def move(self,event):
        if not self.drag_origin:return
        px,py,x,y=self.drag_origin
        self.root.geometry(f'{x+event.x_root-px:+d}{y+event.y_root-py:+d}')

    def begin_resize(self,event):
        self.resize_origin=(event.x_root,event.y_root,self.root.winfo_width(),self.root.winfo_height())

    def resize(self,event):
        if not self.resize_origin:return
        px,py,w,h=self.resize_origin
        mw,mh=self.root.minsize()
        w=max(mw,min(self.root.winfo_screenwidth(),w+event.x_root-px))
        h=max(mh,min(self.root.winfo_screenheight()-50,h+event.y_root-py))
        self.root.geometry(f'{w}x{h}')

    def exit_expanded(self,event=None):
        expanded=self.fit or self.root.state()=='zoomed' or bool(self.root.attributes('-fullscreen'))
        if not expanded:return
        self.root.attributes('-fullscreen',False)
        self.root.state('normal')
        if self.fit and self.saved_geometry:self.root.geometry(self.saved_geometry)
        self.fit=False
        self.saved_geometry=None
        self.root.update_idletasks()
        self.layout_content()
        return 'break'

    def toggle_mode(self):
        # Native maximize/fullscreen state overrides geometry requests. Leave
        # it first so returning to the hawk restores its normal silhouette.
        self.exit_expanded()
        self.root.update_idletasks()
        if self.mode=='hawk':
            self.hawk_geometry=self.root.geometry()
            self.mode='compact'
            target=self.compact_geometry or f'700x{min(780,self.root.winfo_screenheight()-90)}'
        else:
            self.compact_geometry=self.root.geometry()
            self.mode='hawk'
            target=self.hawk_geometry
        self.apply_mode()
        if target:self.root.geometry(target)
        self.root.update_idletasks()
        self.paint()

    def toggle_fit(self):
        if self.fit or self.root.state()=='zoomed' or bool(self.root.attributes('-fullscreen')):
            self.exit_expanded()
        else:
            self.saved_geometry=self.root.geometry()
            w=self.root.winfo_screenwidth()-40
            h=self.root.winfo_screenheight()-80
            self.root.geometry(f'{w}x{h}+20+20')
            self.fit=True
        self.root.update_idletasks()
        self.layout_content()

    def minimize(self):
        self.root.overrideredirect(False)
        self.root.iconify()
        self.minimized=True

    def restore(self,event):
        if event.widget is self.root and self.minimized and self.root.state()=='normal':
            self.minimized=False
            self.restore_job=self.root.after(20,self.restore_frame)

    def restore_frame(self):
        self.restore_job=None
        self.root.overrideredirect(self.mode=='hawk')
        self.layout_content()

    def close(self):
        self.on_close()

    def destroyed(self,event):
        if event.widget is not self.root:return
        for job in (self.paint_job,self.restore_job):
            if job:
                try:self.root.after_cancel(job)
                except tk.TclError:pass
        self.photo=None
        self.mouth_photo=None
        self.open_art=None
        self.art=None
