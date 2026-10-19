"""One-click local PDF export of a tutor response using the working math engine."""
from datetime import datetime
import os
from pathlib import Path
import queue
import re
import threading
import uuid

from hawkes_renderer import Renderer, prepare

FOLDER_NAME = 'Hawkes Companion PDFs'


def desktop_directory():
    """Honor Windows Desktop redirection, including OneDrive Desktop folders."""
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        class GUID(ctypes.Structure):
            _fields_=[('data1',wintypes.DWORD),('data2',wintypes.WORD),
                      ('data3',wintypes.WORD),('data4',ctypes.c_ubyte*8)]
        guid=GUID.from_buffer_copy(uuid.UUID('B4BFCC3A-DB2C-424C-B029-7FE99A87C641').bytes_le)
        value=ctypes.c_wchar_p()
        shell=ctypes.windll.shell32
        shell.SHGetKnownFolderPath.argtypes=[ctypes.POINTER(GUID),wintypes.DWORD,wintypes.HANDLE,ctypes.POINTER(ctypes.c_wchar_p)]
        shell.SHGetKnownFolderPath.restype=ctypes.c_long
        result=shell.SHGetKnownFolderPath(ctypes.byref(guid),0,None,ctypes.byref(value))
        if result==0 and value.value:
            try:return Path(value.value)
            finally:
                ctypes.windll.ole32.CoTaskMemFree.argtypes=[ctypes.c_void_p]
                ctypes.windll.ole32.CoTaskMemFree(ctypes.cast(value,ctypes.c_void_p))
    fallback=Path.home()/'Desktop'
    if not fallback.is_dir():raise OSError('Windows Desktop could not be located. Your answer is still in the chat.')
    return fallback


def export_directory():
    return desktop_directory()/FOLDER_NAME


def write_pdf(data,folder,stamp=None,stem=None):
    """No overwrite; commit a complete PDF from a temporary file in its folder."""
    folder=Path(folder)
    folder.mkdir(parents=True,exist_ok=True)
    stamp=stamp or datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    stem=stem or 'Hawkes_Notes_'+stamp
    for index in range(10000):
        suffix='' if index==0 else f'_{index+1}'
        path=folder/(stem+suffix+'.pdf')
        try:fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        except FileExistsError:continue
        os.close(fd)
        temporary=folder/('.'+path.stem+'.'+uuid.uuid4().hex+'.tmp')
        try:
            temporary.write_bytes(data)
            os.replace(temporary,path)
            return path
        except Exception:
            temporary.unlink(missing_ok=True)
            path.unlink(missing_ok=True)
            raise
    raise OSError('Too many exports have the same timestamp; please try again.')


PRINT_CSS = r'''
@page {size:Letter; margin:.65in .7in .65in}
* {box-sizing:border-box; -webkit-print-color-adjust:exact; print-color-adjust:exact}
html,body {margin:0!important;padding:0!important;background:#fff!important;color:#233042;
 font-family:Georgia,"Times New Roman",serif!important;font-size:11.25pt!important;line-height:1.52!important}
#message {padding:0!important;overflow:visible!important;overflow-wrap:anywhere}
#paper-header {margin:0 0 22px;padding:0 0 18px;border-bottom:2px solid #176a65;break-inside:avoid}
#paper-header .brand {font:600 8pt/1.4 "Segoe UI",Arial,sans-serif;letter-spacing:1.3px;color:#176a65;text-transform:uppercase}
#paper-header h1 {font:700 23pt/1.17 Georgia,serif;margin:9px 0 9px;color:#172b43;letter-spacing:-.4px}
#paper-header .meta {font:9pt/1.4 "Segoe UI",Arial,sans-serif;color:#647487}
h1,h2,h3,h4,h5,h6 {font-family:"Segoe UI",Arial,sans-serif;line-height:1.25!important;
 color:#172b43;margin:22px 0 9px;break-after:avoid;page-break-after:avoid}
h1 {font-size:18pt} h2 {font-size:15pt} h3 {font-size:13pt} h4 {font-size:12pt} h5,h6 {font-size:11.25pt}
p {margin:8px 0;orphans:3;widows:3}
strong {font-weight:700;color:#172b43}
ul,ol {margin:7px 0 12px;padding-left:24px}
li {padding-left:3px;margin:5px 0;break-inside:avoid}
li>p {margin:5px 0}
hr {border:0;border-top:1px solid #dce4e8;margin:17px 0}
blockquote {margin:12px 0;padding:5px 13px;border-left:3px solid #8ab4ad;color:#405567;break-inside:avoid}
pre {font:9pt/1.45 Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere;
 background:#f3f6f8!important;border:1px solid #e0e7eb;padding:10px;break-inside:avoid}
code {font-family:Consolas,monospace;font-size:.9em}
table {border-collapse:collapse;width:100%;margin:10px 0;font-size:10pt}
thead {display:table-header-group} tr {break-inside:avoid}
td,th {border:1px solid #ccd7df;padding:7px;vertical-align:top}
th {background:#eef4f5!important;text-align:left}
a {color:#176a65;text-decoration:none}
mjx-container[display="true"] {display:block;text-align:center;margin:13px 0!important;break-inside:avoid;page-break-inside:avoid;max-width:100%!important}
mjx-container svg {max-width:100%;height:auto}
mjx-assistive-mml {display:none!important}
.study-section {display:flow-root;margin:10px 0 0}
.study-section>h1,.study-section>h2,.study-section>h3,.study-section>h4,.study-section>h5,.study-section>h6 {margin-top:0}
.study-section.with-rule {border-top:1px solid #dce4e8;padding-top:16px;margin-top:16px}
.offline-image {font:9pt "Segoe UI",Arial,sans-serif;color:#647487}
'''


class PdfRenderer(Renderer):
    """Separate print page; the chat renderer and styles are never modified."""
    def __init__(self):
        super().__init__()
        self.page.add_style_tag(content=PRINT_CSS)
        self.page.emulate_media(media='print')

    def create_pdf(self,text):
        # Corrupted decorative trailing emoji cannot be recovered. Keep the
        # answer text and remove only trailing replacement glyphs/whitespace.
        text=re.sub(r'[\ufffd\s]+$','',text)
        if not text.strip():raise ValueError('There is no tutor response to save yet.')
        if '\ufffd' in text:raise ValueError('The response contains unreadable characters. Please request a fresh response before saving.')
        html,equations=prepare(text)
        self.page.set_viewport_size({'width':682,'height':900})
        # Same bundled MathJax setup, TeX protection and conversion as the chat.
        result=self.page.evaluate(r'''async ({html,equations,date}) => {
          MathJax.texReset();
          const target=document.getElementById('message');target.innerHTML=html;
          const errors=[];
          for (const span of target.querySelectorAll('[data-equation]')) {
            const eq=equations[Number(span.dataset.equation)];
            try {
              const node=await MathJax.tex2svgPromise(eq.tex,{display:eq.display});
              if(node.querySelector('[data-mml-node="merror"], [data-mjx-error]'))throw Error('Unsupported or invalid TeX');
              span.replaceWith(node);
            } catch(error) {errors.push(eq.source);}
          }
          let title='Math study notes';
          const first=target.firstElementChild;
          if(first && /^H[1-6]$/.test(first.tagName) && !first.querySelector('mjx-container')) {
            title=first.textContent.trim().slice(0,120)||title;first.remove();
          }
          let header=document.getElementById('paper-header');
          if(header)header.remove();
          header=document.createElement('header');header.id='paper-header';
          const brand=document.createElement('div');brand.className='brand';brand.textContent='Hawkes Companion / Mathematics';
          const heading=document.createElement('h1');heading.textContent=title;
          const meta=document.createElement('div');meta.className='meta';meta.textContent=date+' · Study notes';
          header.append(brand,heading,meta);target.before(header);document.title=title;
          for(const image of target.querySelectorAll('img')) {
            const note=document.createElement('span');note.className='offline-image';
            note.textContent='[Image: '+(image.alt||'not included in this text export')+']';image.replaceWith(note);
          }
          let section=null,withRule=false;
          for(const element of Array.from(target.children)) {
            if(element.tagName==='HR' && element.nextElementSibling && /^H[1-6]$/.test(element.nextElementSibling.tagName)) {
              element.remove();withRule=true;continue;
            }
            if(/^H[1-6]$/.test(element.tagName)) {
              section=document.createElement('section');
              section.className='study-section'+(withRule?' with-rule':'');
              target.insertBefore(section,element);section.append(element);withRule=false;
            } else if(section) section.append(element);
          }
          await document.fonts.ready;
          await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);
          for(const block of target.querySelectorAll('.study-section')) {
            if(block.getBoundingClientRect().height<650)block.style.breakInside='avoid';
          }
          const widths=[];
          for(const math of target.querySelectorAll('mjx-container[display="true"]')) {
            const svg=math.querySelector('svg');if(!svg)continue;
            // MathJax's width attribute is in ex; measure its unscaled width.
            const original=svg.style.maxWidth;svg.style.maxWidth='none';
            const raw=svg.getBoundingClientRect().width;svg.style.maxWidth=original;
            if(raw>target.clientWidth*1.85)widths.push(raw);
          }
          return {errors,title,tooWide:widths.length};
        }''',{'html':html,'equations':equations,'date':datetime.now().strftime('%B %d, %Y')})
        if result['errors']:
            raise ValueError('One or more equations could not render. No PDF was saved; your response is still in the chat.')
        if result['tooWide']:
            raise ValueError('An equation is too wide to print legibly. No PDF was saved; ask for it in shorter aligned lines.')
        footer='''<div style="font-family:Arial,sans-serif;font-size:9px;color:#728090;width:100%;margin:0 .7in;display:flex;justify-content:space-between"><span>Hawkes Companion · Study notes</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>'''
        data=self.page.pdf(format='Letter',prefer_css_page_size=True,print_background=True,
             display_header_footer=True,header_template='<div></div>',footer_template=footer,
             tagged=True,outline=True)
        if not data.startswith(b'%PDF-'):raise ValueError('The PDF could not be created. Please try again.')
        return data


class PdfExportWorker:
    def __init__(self,jobs):
        self.jobs=jobs
        self.tasks=queue.Queue(maxsize=1)
        self.thread=None
        self.closed=False

    def submit(self,text,folder,callback):
        if self.closed:raise RuntimeError('The companion is closing.')
        self.tasks.put_nowait((str(text),folder,callback))
        if self.thread is None:
            self.thread=threading.Thread(target=self.run,daemon=True)
            self.thread.start()

    def run(self):
        renderer=None
        try:
            while not self.closed:
                try:task=self.tasks.get(timeout=.1)
                except queue.Empty:continue
                text,folder,callback=task
                try:
                    if renderer is None:renderer=PdfRenderer()
                    data=renderer.create_pdf(text)
                    if self.closed:continue
                    path=write_pdf(data,export_directory() if folder is None else folder)
                    result=(path,None)
                except Exception as exc:
                    result=(None,str(exc))
                    if renderer is not None and not isinstance(exc,(ValueError,OSError)):
                        try:renderer.close()
                        except Exception:pass
                        renderer=None
                if not self.closed:
                    self.jobs.put(lambda cb=callback,res=result:cb(*res))
        finally:
            if renderer:renderer.close()

    def close(self):
        self.closed=True
        if self.thread:self.thread.join(timeout=2)
