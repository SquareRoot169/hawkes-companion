"""Real offline LaTeX exports, failure recovery and the complete PDF Studio flow."""
from dataclasses import replace
from pathlib import Path
import io
import os
import queue
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch
import pypdfium2 as pdfium
from hawkes_latex import PdfOptions, document, compile_document, safe_math, save_document, LatexWorker, load_options, save_options
from Hawkes_AI_Companion import Companion
from test_v06 import SAMPLE_RESPONSE

class LatexTests(unittest.TestCase):
    def test_math_and_markdown_are_real_latex_offline(self):
        data=compile_document(document(SAMPLE_RESPONSE,PdfOptions(title='Systems',author='Example Author')))
        with pdfium.PdfDocument(data) as pdf:
            self.assertEqual(len(pdf),2)
            text=''.join(p.get_textpage().get_text_range() for p in pdf)
            self.assertIn('Systems',text);self.assertIn('Example Author',text)
            self.assertIn('76',text);self.assertIn('16',text)
            self.assertNotIn('###',text);self.assertNotIn('**',text)
            # A worked step should not begin on one page and spill its formula onto another.
            pages=[p.get_textpage().get_text_range() for p in pdf]
            self.assertIn('Step 3',pages[1]);self.assertNotIn('Step 3',pages[0])
    def test_short_answer_and_professional_controls(self):
        opt=PdfOptions(title='Arithmetic',author='A & B',date='',size=12,accent='Navy',numbers=True,pages=False,paper='A4',template='Lecture notes')
        source=document('$$2+2=4$$',opt)
        self.assertIn(r'\begin{equation}',source)
        self.assertNotIn(r'\fancyfoot[C]',source)
        data=compile_document(source)
        with pdfium.PdfDocument(data) as pdf:
            self.assertEqual(len(pdf),1)
            text=pdf[0].get_textpage().get_text_range()
            self.assertIn('Arithmetic',text);self.assertIn('(1)',text);self.assertIn('A & B',text)
            self.assertAlmostEqual(pdf[0].get_width(),595.28,delta=1)
    def test_content_is_not_executable_tex(self):
        for dangerous in (r'\input{secret}',r'\write18{whoami}',r'\csname input\endcsname',r'\catcode`\%=12',r'\begin{document}x\end{document}',r'\def\x{x}',r'\openin1=secret',r'^^5cinput{secret}'):
            with self.subTest(command=dangerous),self.assertRaises(ValueError):safe_math(dangerous)
        source=document('Literal: \\input{private} <script>alert(1)</script>\n\nPrice: $153.60 and $7.70 per pound.',PdfOptions())
        self.assertIn(r'\textbackslash{}input\{private\}',source)
        self.assertIn(r'\$153.60',source)
        data=compile_document(source)
        self.assertTrue(data.startswith(b'%PDF-'))
    def test_invalid_and_wide_equations_fail_then_retry(self):
        for text in (r'$$\frac{1}$$',r'$$'+('x+'*170)+'1$$'):
            with self.subTest(text=text[:30]),self.assertRaises(ValueError):compile_document(document(text,PdfOptions()))
        self.assertTrue(compile_document(document('$x=2$',PdfOptions())).startswith(b'%PDF-'))
    def test_tables_matrices_and_graphs_offline(self):
        from matplotlib.figure import Figure
        fig=Figure(figsize=(5,3));ax=fig.subplots();ax.plot([0,1,2],[0,1,4]);out=io.BytesIO();fig.savefig(out,format='pdf')
        text=r'''## Matrices
$$\begin{bmatrix}1&2\\3&4\end{bmatrix}\begin{pmatrix}x\\y\end{pmatrix}$$

| Name | Value |
|---|---|
| Cost | $1.25 per item |
'''
        data=compile_document(document(text,PdfOptions(graphs=True),True),out.getvalue())
        with pdfium.PdfDocument(data) as pdf:
            text=''.join(p.get_textpage().get_text_range() for p in pdf)
            self.assertIn('Graph',text);self.assertIn('Cost',text);self.assertIn('1.25',text)
    def test_filename_preferences_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            options=PdfOptions(filename='Algebra / notes.pdf',date='')
            a=save_document(b'%PDF-test',options,folder);b=save_document(b'%PDF-next',options,folder)
            self.assertEqual(a.name,'Algebra _ notes.pdf');self.assertNotEqual(a,b)
            self.assertEqual(a.read_bytes(),b'%PDF-test')
            with patch('hawkes_latex.BASE',folder):
                save_options(options);self.assertEqual(load_options().date,'')
                self.assertEqual(load_options().filename,options.filename)
    def test_worker_recovers_without_altering_text(self):
        jobs=queue.Queue();worker=LatexWorker(jobs);result=[]
        try:
            worker.submit(r'$$\input{secret}$$',PdfOptions(),None,lambda *r:result.append(r))
            self.pump_jobs(jobs,lambda:len(result)==1)
            self.assertIsNotNone(result[0][1])
            worker.submit('$$2+2=4$$',PdfOptions(),None,lambda *r:result.append(r))
            self.pump_jobs(jobs,lambda:len(result)==2)
            self.assertIsNone(result[1][1]);self.assertTrue(result[1][0].startswith(b'%PDF-'))
        finally:worker.close()
    def test_studio_preview_exact_save_dirty_settings_and_graph(self):
        root=tk.Tk()
        with patch.object(Companion,'refresh'):app=Companion(root)
        try:
            app.root.attributes('-topmost',False)
            app.set_pdf_response('## Answer\n$$2+2=4$$')
            app.entry.insert('1.0','Keep my next question')
            before=list(app.history)
            with tempfile.TemporaryDirectory() as directory,patch('hawkes_pdf_studio.save_options'):
                app.pdf_folder_override=Path(directory)/'PDFs'
                app.open_pdf_studio();studio=app.pdf_studio
                studio.window.attributes('-topmost',False)
                self.pump_tk(root,lambda:studio.data is not None)
                self.assertEqual(len(studio.document),1);self.assertIsNotNone(studio.photo)
                studio.save();self.assertEqual(app.last_pdf.read_bytes(),studio.data)
                studio.vars['title'].set('My new title');studio.vars['filename'].set('My study notes')
                studio.save();self.pump_tk(root,lambda:not studio.busy)
                self.assertEqual(app.last_pdf.name,'My study notes.pdf')
                self.assertEqual(app.last_pdf.read_bytes(),studio.data)
                self.assertIn('My new title',studio.document[0].get_textpage().get_text_range())
                app.open_graph();studio.capture_graph();studio.generate()
                self.pump_tk(root,lambda:not studio.busy)
                self.assertTrue(studio.compiled_options.graphs)
                text=''.join(p.get_textpage().get_text_range() for p in studio.document)
                self.assertIn('Graph',text)
                self.assertEqual(app.history,before);self.assertIn('Keep my next question',app.entry.get('1.0','end'))
                studio.zoom.set('125%');studio.redraw();studio.turn(1);studio.close()
                self.assertTrue(studio.closed)
        finally:app.close()
    def test_studio_controls_fit_small_and_high_dpi(self):
        from tkinter import ttk
        for scaling in (1.33,2.0):
            root=tk.Tk();root.tk.call('tk','scaling',scaling)
            with patch.object(Companion,'refresh'):app=Companion(root)
            try:
                app.set_pdf_response('$$2+2=4$$')
                with patch('hawkes_pdf_studio.PdfStudio.generate'):
                    app.open_pdf_studio();studio=app.pdf_studio
                    studio.window.geometry('800x640');root.update()
                    controls=[studio.preview_button,studio.save_button,studio.latex_button]
                    for widget in controls:
                        x=widget.winfo_rootx()-studio.window.winfo_rootx();y=widget.winfo_rooty()-studio.window.winfo_rooty()
                        self.assertGreaterEqual(x,0);self.assertGreaterEqual(y,0)
                        self.assertLessEqual(x+widget.winfo_width(),studio.window.winfo_width())
                        self.assertLessEqual(y+widget.winfo_height(),studio.window.winfo_height())
                    self.assertGreater(studio.canvas.winfo_width(),200)
            finally:app.close()
    def pump_jobs(self,jobs,done):
        end=time.time()+45
        while time.time()<end:
            try:jobs.get(timeout=.05)()
            except queue.Empty:pass
            if done():return
        self.fail('LaTeX worker timed out')
    def pump_tk(self,root,done):
        end=time.time()+45
        while time.time()<end:
            root.update()
            if done():return
            time.sleep(.02)
        self.fail('PDF Studio timed out')

if __name__=='__main__':unittest.main(verbosity=2)
