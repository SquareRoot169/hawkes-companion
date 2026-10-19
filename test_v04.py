"""Currency regression and real Tk hawk-shell checks; no Ollama required."""
from pathlib import Path
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch
from PIL import Image
from hawkes_renderer import prepare, Renderer
from hawk_shell import HawkShell, KEY
from Hawkes_AI_Companion import Companion

WORD_PROBLEM = r'''#### Step 2: Translate the Problem into Equations
**Labor cost + Raw materials cost = Total production cost**
##### First Product:
- Requires **6.5 hours** of labor and **11 pounds** of raw materials.
- Total cost = $153.60.
→ Equation: \( 6.5L + 11R = 153.60 \)
##### Second Product:
- Requires **5.5 hours** of labor and **12 pounds** of raw materials.
- Total cost = $150.70.
→ Equation: \( 5.5L + 12R = 150.70 \)
Now we have a **system of two equations**:
$$
\begin{cases}
6.5L + 11R = 153.60 \quad \text{(1)} \\
5.5L + 12R = 150.70 \quad \text{(2)}
\end{cases}
$$
'''

class CurrencyTests(unittest.TestCase):
    def test_currency_and_math_delimiters(self):
        cases = [('$5 and $10',0),('$5–$10',0),('$153.60.\n\n$150.70.',0),
                 ('It costs $5.00. Use $x=2$ to solve.',1),
                 ('$2x=4$',1),('$2$',1),('$153.60$',1),('$$2x=4$$',1),
                 (r'Escaped \$5 and \(x=2\).',1),
                 ('`$5 and $10`\n```text\n$5 and $10\n```',0),
                 (r'Use $\frac{1}{2}$ and $x^2$ with $10 of materials.',2)]
        for text,count in cases:
            with self.subTest(text=text):
                html,equations=prepare(text)
                self.assertEqual(len(equations),count)
        html,equations=prepare(WORD_PROBLEM)
        self.assertEqual(len(equations),3)
        self.assertIn('<h5>Second Product:</h5>',html)
        self.assertIn('<strong>5.5 hours</strong>',html)
        self.assertIn('$153.60',html)
        self.assertIn('$150.70',html)

    def test_original_word_problem_renders(self):
        renderer=Renderer()
        try:
            images,errors=renderer.render(WORD_PROBLEM,580)
            self.assertEqual(errors,[])
            self.assertEqual(renderer.page.locator('mjx-container').count(),3)
            self.assertEqual(renderer.page.locator('h5').count(),2)
            self.assertIn('$153.60',renderer.page.locator('#message').inner_text())
            renderer.page.screenshot(path=str(Path(__file__).parent/'word_problem_verified.png'),full_page=True)
        finally:renderer.close()

class HawkTests(unittest.TestCase):
    def test_shell_layout_modes_and_context(self):
        root=tk.Tk()
        root.tk.call('tk','scaling',2.0)
        shell=HawkShell(root)
        with patch.object(Companion,'refresh'):
            app=Companion(root,surface=shell.content)
        shell.on_close=app.close
        shell.start()
        root.attributes('-topmost',False)
        root.update()
        try:
            self.assertTrue(root.overrideredirect())
            self.assertEqual(str(root.attributes('-transparentcolor')),KEY)
            self.assertEqual(shell.art.getextrema()[3],(0,255))
            app.history=[{'role':'user','content':'Keep this conversation'}]
            app.entry.insert('1.0','Keep this draft')
            app.set_image(Image.new('RGB',(300,150)),'Test attachment')
            for size in ('1040x980','920x780'):
                root.geometry(size)
                root.update()
                # Small centers automatically fold settings, all actions still fit.
                self.check_buttons(shell.content)
                self.assertGreater(app.chat.winfo_height(),40)
                self.assertLess(shell.content.winfo_width(),root.winfo_width())
                self.assertGreater(shell.content.winfo_x(),0)
                self.assertGreater(shell.content.winfo_y(),0)
            self.assertFalse(app.settings_visible)
            app.toggle_settings();root.update()
            self.assertTrue(app.settings_visible)
            app.toggle_settings();root.update()
            shell.toggle_mode();root.update()
            self.assertEqual(shell.mode,'compact')
            self.assertFalse(root.overrideredirect())
            self.assertEqual(str(root.attributes('-transparentcolor')),'')
            self.check_buttons(shell.content)
            self.assertEqual(app.history[0]['content'],'Keep this conversation')
            self.assertEqual(app.entry.get('1.0','end').strip(),'Keep this draft')
            self.assertTrue(app.pending)
            shell.toggle_mode();root.update()
            self.assertTrue(root.overrideredirect())
            shell.minimize();root.update()
            self.assertEqual(root.state(),'iconic')
            root.deiconify()
            for _ in range(8):root.update();time.sleep(.025)
            self.assertTrue(root.overrideredirect())
            self.assertEqual(root.state(),'normal')
        finally:app.close()

    def check_buttons(self,parent):
        def children(widget):
            for child in widget.winfo_children():
                yield child
                yield from children(child)
        for widget in children(parent):
            if isinstance(widget,ttk.Button) and widget.winfo_ismapped():
                x=widget.winfo_rootx()-parent.winfo_rootx()
                y=widget.winfo_rooty()-parent.winfo_rooty()
                with self.subTest(control=widget.cget('text')):
                    self.assertGreaterEqual(x,0)
                    self.assertGreaterEqual(y,0)
                    self.assertLessEqual(x+widget.winfo_width(),parent.winfo_width())
                    self.assertLessEqual(y+widget.winfo_height(),parent.winfo_height())
                    self.assertGreaterEqual(widget.winfo_width(),widget.winfo_reqwidth())

if __name__=='__main__':unittest.main(verbosity=2)
