"""Complete editable LaTeX source, assets, safe saves and current UI settings."""
from pathlib import Path
from dataclasses import replace
import tempfile,unittest,tkinter as tk
from unittest.mock import patch
from hawkes_latex import PdfOptions,save_latex_source,compile_document,document
from Hawkes_AI_Companion import Companion
from test_factorial_math import EXAMPLE

class TexExportTests(unittest.TestCase):
    def test_complete_source_compiles_offline_and_preserves_options(self):
        options=PdfOptions(title='Editable notes',author='Example Author',size=12,accent='Teal',numbers=True,paper='A4')
        with tempfile.TemporaryDirectory() as folder:
            path=save_latex_source(EXAMPLE,options,folder=folder)
            source=path.read_text(encoding='utf-8')
            self.assertEqual(source,document(EXAMPLE,options))
            self.assertIn(r'\documentclass[12pt,a4paper]',source)
            self.assertIn(r'\begin{document}',source);self.assertIn(r'\end{document}',source)
            self.assertTrue(compile_document(source).startswith(b'%PDF-'))
            self.assertFalse((path.parent/'graph.pdf').exists())
    def test_graph_is_portable_and_export_never_overwrites(self):
        from matplotlib.figure import Figure
        import io
        fig=Figure(figsize=(4,2));fig.subplots().plot([0,1],[0,1]);buffer=io.BytesIO();fig.savefig(buffer,format='pdf')
        with tempfile.TemporaryDirectory() as folder:
            opt=PdfOptions(graphs=True,filename='../Unsafe / name.tex',caption='Selected graph')
            a=save_latex_source('$x=2$',opt,buffer.getvalue(),folder)
            b=save_latex_source('$x=3$',opt,buffer.getvalue(),folder)
            self.assertNotEqual(a.parent,b.parent)
            self.assertEqual(a.parent.parent,Path(folder))
            self.assertEqual((a.parent/'graph.pdf').read_bytes(),buffer.getvalue())
            self.assertIn('{graph.pdf}',a.read_text())
            self.assertTrue(compile_document(a.read_text(),(a.parent/'graph.pdf').read_bytes()).startswith(b'%PDF-'))
            with self.assertRaises(ValueError):save_latex_source('$x=2$',opt,folder=folder)
    def test_write_failure_cleans_own_folder_and_keeps_existing_files(self):
        with tempfile.TemporaryDirectory() as folder:
            existing=Path(folder)/'Existing.tex';existing.write_text('keep')
            with patch.object(Path,'write_bytes',side_effect=OSError('Disk full')):
                with self.assertRaises(OSError):save_latex_source('$x=2$',PdfOptions(),folder=folder)
            self.assertEqual(list(Path(folder).iterdir()),[existing])
    def test_button_exports_current_settings_without_waiting_for_preview(self):
        root=tk.Tk()
        with patch.object(Companion,'refresh'):app=Companion(root)
        try:
            with tempfile.TemporaryDirectory() as folder,patch('hawkes_pdf_studio.save_options'),patch('hawkes_pdf_studio.PdfStudio.generate'):
                app.pdf_folder_override=Path(folder)
                app.set_pdf_response(EXAMPLE);app.open_pdf_studio();s=app.pdf_studio
                s.fields['title'].delete(0,'end');s.fields['title'].insert(0,'My Overleaf document')
                s.vars['size'].set('12');s.busy=True
                s.latex_button.invoke()
                self.assertTrue(s.last_latex.is_file())
                source=s.last_latex.read_text(encoding='utf-8')
                self.assertIn('My Overleaf document',source);self.assertIn('[12pt,',source)
                self.assertEqual(app.pdf_text,EXAMPLE)
                self.assertIsNone(app.last_pdf)
        finally:app.close()

if __name__=='__main__':unittest.main(verbosity=2)
