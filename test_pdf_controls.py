"""Regression checks for actual widget choices and every PDF option's result."""
from dataclasses import replace
import ctypes
from pathlib import Path
import tempfile,time,tkinter as tk,unittest
from unittest.mock import patch
import pypdfium2 as pdfium
from pypdfium2 import raw
from hawkes_latex import PdfOptions,document,compile_document,TEMPLATES
from hawkes_pdf_studio import PdfStudio
from Hawkes_AI_Companion import Companion
from test_v06 import SAMPLE_RESPONSE

class ControlTests(unittest.TestCase):
    def objects(self,data):
        result=[]
        with pdfium.PdfDocument(data) as pdf:
            for page in pdf:
                textpage=page.get_textpage()
                try:
                    for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_TEXT],textpage=textpage):
                        result.append((obj.extract(),obj.get_font_size(),obj.get_font().get_base_name(),obj.get_bounds()))
                finally:textpage.close()
        return result

    def test_all_sizes_templates_and_margins_offline(self):
        # Each combination uses the actual worked response, including nested
        # lists and TS1 symbols that were absent from the first version's tests.
        for size in (10,11,12):
            for template in TEMPLATES:
                for margin in ('Standard','Generous','Compact'):
                    with self.subTest(size=size,template=template,margin=margin):
                        options=PdfOptions(size=size,template=template,margins=margin)
                        data=compile_document(document(SAMPLE_RESPONSE,options))
                        self.assertTrue(data.startswith(b'%PDF-'))
    def test_each_appearance_control_changes_the_pdf(self):
        text='### A mathematical heading\nA sentence for measuring text size and placement.\n\n$$x+2=4$$'
        base=PdfOptions(title='',author='',date='',pages=False)
        results={}
        cases={'base':base,'size':replace(base,size=12),'small':replace(base,size=10),'template':replace(base,template='Lecture notes'),
               'margins':replace(base,margins='Generous'),'paper':replace(base,paper='A4'),
               'compact':replace(base,margins='Compact'),'navy':replace(base,accent='Navy'),
               'accent':replace(base,accent='Teal'),'numbers':replace(base,numbers=True),'pages':replace(base,pages=True)}
        for name,opt in cases.items():results[name]=compile_document(document(text,opt))
        def get_run(name,prefix):return next(obj for obj in self.objects(results[name]) if obj[0].startswith(prefix))
        self.assertGreater(get_run('size','A sentence')[1],get_run('base','A sentence')[1])
        self.assertLess(get_run('small','A sentence')[1],get_run('base','A sentence')[1])
        self.assertNotEqual(get_run('template','A mathematical')[2],get_run('base','A mathematical')[2])
        self.assertGreater(get_run('margins','A sentence')[3][0],get_run('base','A sentence')[3][0]+10)
        self.assertLess(get_run('compact','A sentence')[3][0],get_run('base','A sentence')[3][0]-10)
        with pdfium.PdfDocument(results['paper']) as pdf:self.assertAlmostEqual(pdf[0].get_width(),595.28,delta=1)
        with pdfium.PdfDocument(results['numbers']) as pdf:self.assertIn('(1)',pdf[0].get_textpage().get_text_range())
        # A visible footer and visibly colored heading, not just a source flag.
        with pdfium.PdfDocument(results['pages']) as pdf:self.assertTrue(pdf[0].get_textpage().get_text_range().rstrip().endswith('1'))
        for case,expected in [('accent',(23,106,101)),('navy',(24,52,77))]:
            colors=[]
            with pdfium.PdfDocument(results[case]) as pdf:
                for obj in pdf[0].get_objects(filter=[raw.FPDF_PAGEOBJ_TEXT]):
                    values=[ctypes.c_uint() for _ in range(4)]
                    if raw.FPDFPageObj_GetFillColor(obj,*[ctypes.byref(v) for v in values]):colors.append(tuple(v.value for v in values[:3]))
            self.assertIn(expected,colors)
    def test_widget_selections_live_update_without_manual_refresh(self):
        root=tk.Tk()
        with patch.object(Companion,'refresh'):app=Companion(root)
        try:
            with patch('hawkes_pdf_studio.save_options'),patch('hawkes_pdf_studio.load_options',return_value=PdfOptions()):
                app.set_pdf_response('### Worked result\nA short explanation.\n\n$$x=2$$')
                app.open_pdf_studio();s=app.pdf_studio
                self.wait(root,lambda:s.data is not None and not s.busy)
                s.notebook.select(s.appearance_tab);root.update()
                # Open the real ttk dropdown, select through its Listbox class
                # binding and commit through the same Return event as a user.
                self.select(root,s.choices['size'],'12')
                self.select(root,s.choices['template'],'Lecture notes')
                self.select(root,s.choices['accent'],'Teal')
                self.select(root,s.choices['margins'],'Generous')
                self.select(root,s.choices['paper'],'A4')
                self.click(s.number_check);self.click(s.page_check)
                self.wait(root,lambda:s.compiled_revision==s.revision and not s.busy)
                opt=s.compiled_options
                self.assertEqual((opt.size,opt.template,opt.accent,opt.margins,opt.paper),(12,'Lecture notes','Teal','Generous','A4'))
                self.assertTrue(opt.numbers);self.assertFalse(opt.pages)
                self.assertIn('(1)',s.document[0].get_textpage().get_text_range())
                width=s.photo.width();self.select(root,s.zoom_choice,'125%');root.update()
                self.assertGreater(s.photo.width(),width)
                self.select(root,s.zoom_choice,'Fit width')
                s.notebook.select(s.document_tab);root.update()
                field=s.fields['author'];field.delete(0,'end');field.insert(0,'Author from the form')
                self.wait(root,lambda:s.compiled_revision==s.revision and not s.busy)
                self.assertIn('Author from the form',s.document[0].get_textpage().get_text_range())
                s.fields['date'].delete(0,'end');s.fields['title'].delete(0,'end')
                self.wait(root,lambda:s.compiled_revision==s.revision and not s.busy)
                self.assertEqual(s.compiled_options.date,'');self.assertEqual(s.compiled_options.title,'')
                with tempfile.TemporaryDirectory() as folder:
                    app.pdf_folder_override=Path(folder)
                    s.fields['filename'].delete(0,'end');s.fields['filename'].insert(0,'My chosen filename')
                    self.click(s.save_button);root.update()
                    self.assertEqual(app.last_pdf.name,'My chosen filename.pdf')
                    self.assertEqual(app.last_pdf.read_bytes(),s.data)
        finally:app.close()
    def test_changes_during_compilation_and_save_are_not_lost(self):
        class HeldWorker:
            def __init__(self,*_):self.calls=[]
            def submit(self,*args):self.calls.append(args)
            def close(self):pass
        root=tk.Tk()
        with patch.object(Companion,'refresh'):app=Companion(root)
        try:
            with tempfile.TemporaryDirectory() as folder,patch('hawkes_pdf_studio.LatexWorker',HeldWorker),patch('hawkes_pdf_studio.save_options'):
                app.pdf_folder_override=Path(folder);app.set_pdf_response('$$2+2=4$$');app.open_pdf_studio();s=app.pdf_studio
                self.wait(root,lambda:len(s.worker.calls)==1)
                s.fields['title'].delete(0,'end');s.fields['title'].insert(0,'The latest title')
                self.click(s.save_button)
                self.assertTrue(s.save_requested)
                text,opt,graph,callback=s.worker.calls[0]
                callback(compile_document(document(text,opt)),None)
                self.assertIsNone(s.data);self.assertIsNone(app.last_pdf)
                self.assertEqual(len(s.worker.calls),2)
                text,opt,graph,callback=s.worker.calls[-1]
                self.assertEqual(opt.title,'The latest title')
                callback(compile_document(document(text,opt)),None)
                self.assertTrue(app.last_pdf.is_file());self.assertEqual(s.data,app.last_pdf.read_bytes())
                self.assertIn('The latest title',s.document[0].get_textpage().get_text_range())
        finally:app.close()
    def test_filename_survives_reopen_and_folder_button(self):
        root=tk.Tk()
        with patch.object(Companion,'refresh'):app=Companion(root)
        try:
            with patch('hawkes_pdf_studio.load_options',return_value=PdfOptions(filename='My semester notes')),patch.object(PdfStudio,'generate'):
                app.set_pdf_response('$x=2$');app.open_pdf_studio();s=app.pdf_studio
                self.assertEqual(s.vars['filename'].get(),'My semester notes')
                with tempfile.TemporaryDirectory() as folder,patch('hawkes_pdf_studio.os.startfile') as launch:
                    app.pdf_folder_override=Path(folder)/'New PDF folder';s.open_folder()
                    self.assertTrue(app.pdf_folder_override.is_dir());launch.assert_called_once_with(str(app.pdf_folder_override))
        finally:app.close()
    def test_graph_toggle_uses_current_plot_and_omits_when_off(self):
        root=tk.Tk()
        with patch.object(Companion,'refresh'):app=Companion(root)
        try:
            with patch('hawkes_pdf_studio.save_options'),patch('hawkes_pdf_studio.load_options',return_value=PdfOptions()):
                app.set_pdf_response('$$y=x^2$$');app.open_pdf_studio();s=app.pdf_studio
                self.wait(root,lambda:s.data is not None and not s.busy)
                s.open_graph();self.assertEqual(str(app.graph_window.window.transient()),str(s.window))
                s.notebook.select(s.graphs_tab);root.update();self.click(s.graph_check)
                s.fields['caption'].delete(0,'end');s.fields['caption'].insert(0,'My selected graph caption')
                self.wait(root,lambda:s.compiled_revision==s.revision and not s.busy)
                text=''.join(page.get_textpage().get_text_range() for page in s.document)
                self.assertIn('My selected graph caption',text)
                self.click(s.graph_check);self.wait(root,lambda:s.compiled_revision==s.revision and not s.busy)
                text=''.join(page.get_textpage().get_text_range() for page in s.document)
                self.assertNotIn('My selected graph caption',text)
        finally:app.close()
    def test_preview_page_buttons_move_and_show_boundaries(self):
        root=tk.Tk()
        with patch.object(Companion,'refresh'):app=Companion(root)
        try:
            with patch('hawkes_pdf_studio.save_options'),patch('hawkes_pdf_studio.load_options',return_value=PdfOptions()):
                app.set_pdf_response(SAMPLE_RESPONSE);app.open_pdf_studio();s=app.pdf_studio
                self.wait(root,lambda:s.data is not None and not s.busy)
                self.assertGreater(len(s.document),1)
                self.assertEqual(str(s.previous_button['state']),'disabled')
                self.click(s.next_button);root.update();self.assertEqual(s.page,1)
                self.click(s.previous_button);root.update();self.assertEqual(s.page,0)
        finally:app.close()
    def select(self,root,combo,value):
        combo.focus_force();combo.event_generate('<ButtonPress-1>',x=combo.winfo_width()-8,y=combo.winfo_height()//2)
        root.update()
        popdown=root.tk.call('ttk::combobox::PopdownWindow',str(combo))
        def find(widget):
            if root.tk.call('winfo','class',widget)=='Listbox':return widget
            for child in root.tk.splitlist(root.tk.call('winfo','children',widget)):
                result=find(child)
                if result:return result
        lb=find(popdown);self.assertTrue(lb)
        index=list(combo['values']).index(value)
        root.tk.call(lb,'selection','clear',0,'end');root.tk.call(lb,'selection','set',index)
        root.tk.call('event','generate',lb,'<Return>');root.update()
        self.assertEqual(combo.get(),value)
    def click(self,widget):
        widget.event_generate('<Enter>');widget.event_generate('<ButtonPress-1>',x=8,y=8)
        widget.event_generate('<ButtonRelease-1>',x=8,y=8)
    def wait(self,root,predicate):
        end=time.time()+45
        while time.time()<end:
            root.update()
            if predicate():return
            time.sleep(.02)
        self.fail('PDF controls did not finish updating')

if __name__=='__main__':unittest.main(verbosity=2)
