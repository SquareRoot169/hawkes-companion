"""Run with the app's Python: python test_rendering.py. No Ollama required."""
import base64
import io
from pathlib import Path
import time
import tkinter as tk
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
from hawkes_renderer import Renderer, prepare
from Hawkes_AI_Companion import Companion, GraphWindow, evaluate, encode_image, STYLES

CASES = {
    'boxed': r'Final answer: $\boxed{x=\frac{3}{2}}$.',
    'bmatrix': r'$$A=\begin{bmatrix}1&2\\3&4\end{bmatrix}$$',
    'aligned': r'\[\begin{aligned}2x+3&=7\\2x&=4\\x&=2\end{aligned}\]',
    'cases': r'$$f(x)=\begin{cases}x^2 & x\geq0\\-x & x<0\end{cases}$$',
    'fractions': r'Inline \(\dfrac{1}{1+\frac{1}{x}}\) and $\tfrac{a}{b}$.',
    'qwen_multiline': r'''## Solve the system
**Step 1:** Write the augmented matrix.

$$
\begin{bmatrix}1&1&3\\2&-1&0\end{bmatrix}
$$

1. Eliminate a variable.
2. Substitute back:

\[
\begin{aligned}
3x &= 3 \\
x &= 1 \\
y &= 2
\end{aligned}
\]

The result is **exactly** $\boxed{(1,2)}$.
''',
    'bare_align': r'\begin{align}x&=1\\y&=2\end{align}',
    'latex_fence': '```latex\n\\boxed{\\frac{1}{2}}\n```',
    'code_literal': 'Use `x_1` and **bold**.\n```python\nprint("$not_math$")\n```',
    'escaped_currency': r'The cost is \$5. Math: $x_1=2$.',
}


class RenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.renderer = Renderer()

    @classmethod
    def tearDownClass(cls):
        cls.renderer.close()

    def test_representative_equations(self):
        folder = Path(__file__).parent / 'test-previews'
        folder.mkdir(exist_ok=True)
        for name, text in CASES.items():
            with self.subTest(name=name):
                images, errors = self.renderer.render(text, 580)
                self.assertEqual(errors, [])
                self.assertTrue(images)
                self.assertGreater(images[0].height, 20)
                preview = Image.new('RGB', (max(im.width for im in images), sum(im.height for im in images)), 'white')
                y = 0
                for im in images:
                    preview.paste(im, (0, y))
                    y += im.height
                preview.save(folder / (name + '.png'))
                if name not in ('code_literal',):
                    self.assertGreater(self.renderer.page.locator('mjx-container svg').count(), 0)
        html, equations = prepare(CASES['qwen_multiline'])
        self.assertIn('<h2>', html)
        self.assertIn('<strong>', html)
        self.assertIn('<ol>', html)
        self.assertEqual(len(equations), 3)
        self.assertIn(r'\\', equations[1]['tex'])

    def test_error_preserves_source(self):
        source = r'$\definitelyNotACommand{x}$'
        _, errors = self.renderer.render(source)
        self.assertTrue(errors)
        self.assertIn(source, self.renderer.page.locator('#message').inner_text())

    def test_html_and_network_are_blocked(self):
        requests = []
        self.renderer.page.on('request', lambda req: requests.append(req.url))
        self.renderer.render('<script>window.hacked=true</script>\n![remote](https://example.com/x.png)')
        self.assertIsNone(self.renderer.page.evaluate('window.hacked'))
        self.assertEqual(self.renderer.page.locator('script').count(), 1)  # bundled MathJax only
        self.assertTrue(all(url.startswith('https://example.com/') for url in requests))
        self.assertEqual(self.renderer.page.locator('img').evaluate('(img)=>img.naturalWidth'), 0)

    def test_long_and_wide(self):
        images, errors = self.renderer.render(('A paragraph with $x^2$.\n\n' * 150))
        self.assertFalse(errors)
        self.assertGreater(len(images), 1)
        self.assertTrue(all(im.height <= 160 for im in images))
        images, errors = self.renderer.render('$$' + '+'.join(['x'] * 100) + '$$')
        self.assertFalse(errors)
        self.assertGreater(images[0].width, 580)


class AppTests(unittest.TestCase):
    def test_graph_and_images(self):
        np.testing.assert_allclose(evaluate('2*x^2-3', np.array([0., 2.])), [-3, 5])
        with self.assertRaises(ValueError):
            evaluate('__import__("os")', np.array([1.]))
        raw = encode_image(Image.new('RGB', (2500, 1000)))
        with Image.open(io.BytesIO(base64.b64decode(raw))) as im:
            self.assertEqual(im.width, 2048)
        self.assertEqual(len(STYLES), 3)

    def test_tk_ollama_flow_and_reset(self):
        root = tk.Tk()
        root.withdraw()
        with patch.object(Companion, 'refresh'):
            app = Companion(root)
        self.addCleanup(app.close)
        app.model.set('test-local')
        app.api = lambda endpoint, payload=None: {'message': {'content': CASES['qwen_multiline']}}
        app.entry.insert('1.0', 'Solve this')
        app.send()
        deadline = time.time() + 40
        while time.time() < deadline:
            root.update()
            if not app.busy and not app.chat.get('1.0', 'end').count('Formatting response'):
                break
            time.sleep(.03)
        self.assertFalse(app.busy)
        self.assertEqual(len(app.history), 2)
        self.assertTrue(app.photos)
        app.copy_reply()
        self.assertEqual(root.clipboard_get(), CASES['qwen_multiline'])
        app.add('assistant', '$x^2$')
        app.clear()  # in-flight result must never reappear in the new conversation
        deadline = time.time() + 2
        while time.time() < deadline:
            root.update()
            time.sleep(.03)
        self.assertEqual(app.history, [])
        self.assertNotIn('Solve this', app.chat.get('1.0', 'end'))
        app.set_image(Image.new('RGB', (100, 100)), 'Test attachment')
        self.assertTrue(app.pending)
        app.remove_image()
        self.assertIsNone(app.pending)
        graph = GraphWindow(root)
        graph.plot()
        self.assertEqual(len(graph.axes.lines), 4)
        graph.window.destroy()
        app.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
