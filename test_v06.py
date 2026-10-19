"""Offline PDF export: real MathJax print output, safe saves and UI state."""
from pathlib import Path
import queue
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch
from hawkes_pdf import PdfRenderer, PdfExportWorker, write_pdf, desktop_directory
from hawkes_renderer import prepare
from Hawkes_AI_Companion import Companion

SAMPLE_RESPONSE=r'''### Understanding the Problem
We are given a word problem about two integers. Let's break it down:

- **Key facts**:
  1. The sum of the two integers is 92.
  2. The larger integer is 12 more than 4 times the smaller integer.
- **Goal**: Find the two integers.

---
### Step 1: Define Variables
Let:
- \( x \) = smaller integer
- \( y \) = larger integer

This choice makes sense because we're told the larger integer relates to the smaller one.

---
### Step 2: Translate to Equations
We convert the problem's conditions into mathematical equations.

1. **Sum condition**: The sum of the two integers is 92.
   $$ x + y = 92 $$
2. **Relationship between larger and smaller**: The larger integer is 12 more than 4 times the smaller.
   $$ y = 4x + 12 $$

Now we have a system of two equations:
$$
\begin{cases}
x + y = 92 \\
y = 4x + 12
\end{cases}
$$

---
### Step 3: Solve the System
We'll use **substitution** (since the second equation already solves for \( y \)).

- Substitute \( y = 4x + 12 \) into the first equation:
  $$ x + (4x + 12) = 92 $$
- Simplify:
  $$ 5x + 12 = 92 $$
- Solve for \( x \):
  $$ 5x = 80 \quad \Rightarrow \quad x = 16 $$
- Find \( y \) using \( y = 4x + 12 \):
  $$ y = 4(16) + 12 = 64 + 12 = 76 $$

---
### Step 4: Verify the Solution
- Check the sum: \( 16 + 76 = 92 \) ✅
- Check the relationship: \( 4 \times 16 + 12 = 64 + 12 = 76 \) ✅

Both conditions are satisfied!

---
### Final Answer
- **Larger integer**: \( \boxed{76} \)
- **Smaller integer**: \( \boxed{16} \)

To confirm your work:
- If you're solving this, ask: *What happens if I swap the roles of \( x \) and \( y \) in the relationship equation?*
- If you're unsure about substitution, try **elimination** instead.
'''

class PdfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.renderer=PdfRenderer()
    @classmethod
    def tearDownClass(cls):cls.renderer.close()

    def test_worked_solution_pdf(self):
        data=self.renderer.create_pdf(SAMPLE_RESPONSE+'\n��')
        self.assertTrue(data.startswith(b'%PDF-'))
        self.assertGreater(len(data),15000)
        page=self.renderer.page
        self.assertEqual(page.locator('mjx-container').count(),len(prepare(SAMPLE_RESPONSE)[1]))
        text=page.locator('body').inner_text()
        self.assertNotIn('**',text)
        self.assertNotIn('###',text)
        self.assertNotIn('�',text)
        self.assertGreater(page.locator('ol li').count(),2)
        self.assertEqual(page.locator('#paper-header h1').inner_text(),'Understanding the Problem')
        self.assertIn('Final Answer',text)

    def test_errors_are_not_saved_as_broken_pdfs(self):
        with self.assertRaisesRegex(ValueError,'could not render'):
            self.renderer.create_pdf(r'Bad formula: $\thisCommandDoesNotExist{x}$.')
        with self.assertRaisesRegex(ValueError,'unreadable'):
            self.renderer.create_pdf('Unreadable � data in the middle.')
        with self.assertRaisesRegex(ValueError,'too wide'):
            self.renderer.create_pdf('$$'+'+'.join(['x']*100)+'$$')
        self.assertTrue(self.renderer.create_pdf('## Retry\nA valid answer: $x=2$.').startswith(b'%PDF-'))

    def test_long_response_and_offline_safety(self):
        text='## Long study notes\n'+('\n### Worked example\nA paragraph with $x^2+1$.\n\n'*55)+'\nEND OF NOTES'
        data=self.renderer.create_pdf(text)
        self.assertTrue(data.startswith(b'%PDF-'))
        self.assertIn('END OF NOTES',self.renderer.page.locator('body').inner_text())
        self.renderer.create_pdf('<script>window.hacked=1</script>\n![reference](https://example.com/image.png)')
        self.assertIsNone(self.renderer.page.evaluate('window.hacked'))
        self.assertEqual(self.renderer.page.locator('#message img').count(),0)
        self.assertIn('Image: reference',self.renderer.page.locator('#message').inner_text())

    def test_save_creates_folder_without_overwrite_and_cleans_failures(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'New PDF folder'
            first=write_pdf(b'%PDF-first',folder,stamp='fixed')
            second=write_pdf(b'%PDF-second',folder,stamp='fixed')
            self.assertNotEqual(first,second)
            self.assertEqual(first.read_bytes(),b'%PDF-first')
            self.assertFalse(list(folder.glob('*.tmp')))
            before=set(folder.iterdir())
            with patch('hawkes_pdf.os.replace',side_effect=OSError('Disk unavailable')):
                with self.assertRaises(OSError):write_pdf(b'%PDF-fail',folder,stamp='failure')
            self.assertEqual(set(folder.iterdir()),before)
        self.assertTrue(desktop_directory().is_dir())

    def test_worker_failure_recovery_and_snapshot(self):
        jobs=queue.Queue();results=[]
        worker=PdfExportWorker(jobs)
        try:
            with tempfile.TemporaryDirectory() as temp:
                folder=Path(temp)/'Automatic folder'
                worker.submit(r'$\badCommand{x}$',folder,lambda *r:results.append(r))
                self.wait(jobs,lambda:bool(results))
                self.assertIsNotNone(results[-1][1])
                self.assertFalse(folder.exists())
                worker.submit('## Saved snapshot\nThe result is $x=2$.',folder,lambda *r:results.append(r))
                self.wait(jobs,lambda:len(results)==2)
                self.assertIsNone(results[-1][1])
                self.assertTrue(results[-1][0].is_file())
        finally:worker.close()

    def test_button_uses_real_latest_answer_and_preserves_chat(self):
        root=tk.Tk()
        with patch.object(Companion,'refresh'):app=Companion(root)
        try:
            self.assertEqual(str(app.pdf_button['state']),'disabled')
            app.model.set('test-local')
            app.api=lambda *args,**kwargs:{'message':{'content':'## Final answer\nThe result is $\\boxed{16}$.'}}
            app.entry.insert('1.0','Solve this problem')
            app.send()
            self.wait_tk(root,lambda:not app.busy)
            self.assertEqual(str(app.pdf_button['state']),'normal')
            with tempfile.TemporaryDirectory() as temp:
                app.pdf_folder_override=Path(temp)/'Desktop PDF folder'
                before=list(app.history)
                app.save_pdf()
                app.entry.insert('1.0','My next question')
                self.wait_tk(root,lambda:not app.pdf_busy)
                self.assertTrue(app.last_pdf.is_file())
                self.assertEqual(app.history,before)
                self.assertIn('My next question',app.entry.get('1.0','end'))
                app.clear()
                self.assertEqual(str(app.pdf_button['state']),'disabled')
                self.assertIsNone(app.pdf_text)
        finally:app.close()

    def wait(self,jobs,done,timeout=30):
        end=time.time()+timeout
        while time.time()<end:
            try:
                while True:jobs.get_nowait()()
            except queue.Empty:pass
            if done():return
            time.sleep(.02)
        self.fail('PDF worker timed out')

    def wait_tk(self,root,done,timeout=30):
        end=time.time()+timeout
        while time.time()<end:
            root.update()
            if done():return
            time.sleep(.02)
        self.fail('PDF UI timed out')

if __name__=='__main__':unittest.main(verbosity=2)
