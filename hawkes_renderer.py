"""Offline Markdown + MathJax renderer. All browser calls belong to one worker."""
import io
import os
from pathlib import Path
import queue
import re
import threading

from markdown_it import MarkdownIt
from PIL import Image

BASE = Path(__file__).resolve().parent
# Keep Chromium with the app so another installation cannot replace it.
os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(BASE / 'browser')

# Protect TeX BEFORE Markdown can consume backslashes, underscores or line breaks.
# Code fences and inline code deliberately remain literal.
# Recognize ordinary prices BEFORE inline math so prices cannot consume later
# formula delimiters. Inline math accepts model-added horizontal padding but
# stays on one line; multiline math uses display delimiters.
TOKENS = re.compile(
    r'(?P<code>```[^\n]*\n[\s\S]*?```|~~~[^\n]*\n[\s\S]*?~~~|`[^`\n]+`)'
    r'|(?P<currency>(?<![\\$])\$[ \t]*\d[\d,]*(?:\.\d+)?'
    # A number followed by factorial and an operator/math closer is an
    # expression, not a dollar price followed by sentence punctuation.
    r'(?!\w|\.\d|[ \t]*!(?=[ \t]*(?:=|[+*/^_-]|\\(?:times|cdot|div)(?![A-Za-z])|\$(?!\d))))'
    r'(?=[ \t]*(?:$|[\r\n]|[.,;:!?)]|[-–—/][ \t]*\$)'
    r'|[ \t]+(?:[*_]{1,3})?(?!(?:sin|cos|tan|log|ln|sqrt|exp|lim|max|min|mod)\b)'
    r'(?:[A-Za-z]{2,}\b|a(?=[ \t]+[A-Za-z]{2,}\b))))'
    r'|(?P<math>(?<!\\)\$\$[\s\S]+?(?<!\\)\$\$'
    r'|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)'
    r'|(?<![\\$])\$(?!\$)(?:\\[^\r\n]|[^$\\\r\n])+?(?<!\\)\$(?![\d$])'
    r'|\\begin\{(?P<env>align\*?|aligned|gather\*?|equation\*?|bmatrix|pmatrix|matrix|cases)\}'
    r'[\s\S]+?\\end\{(?P=env)\})')


def prepare(message):
    """Return safe Markdown HTML plus untouched equations, never executable HTML."""
    equations = []
    # Models occasionally wrap formulas in a latex/math fence; unwrap those only.
    message = re.sub(r'```(?:latex|math|tex)\s*\n([\s\S]*?)```',
                     lambda m: '\n$$' + m[1].strip().removeprefix('$$').removesuffix('$$') + '$$\n',
                     message, flags=re.I)
    # Pick a marker absent from the input, including malicious/lookalike output.
    marker = 'HAWKESMATHTOKEN'
    while marker in message:
        marker += 'X'

    def protect(match):
        if match['code'] or match['currency']:
            return match[0]
        raw = match[0]
        display = raw.startswith(('$$', r'\[', r'\begin'))
        if raw.startswith(('$$', r'\[', r'\(')):
            tex = raw[2:-2]
        elif raw.startswith('$'):
            tex = raw[1:-1].strip()
            if not tex:return raw
        else:
            tex = raw
        # aligned and matrix are valid inner environments; align is a top-level one.
        equations.append({'tex': tex, 'display': display, 'source': raw})
        token = f'{marker}{len(equations)-1}END'
        return '\n\n' + token + '\n\n' if display else token

    html = MarkdownIt('commonmark', {'html': False, 'breaks': True}).enable('table').render(
        TOKENS.sub(protect, message))
    for index, eq in enumerate(equations):
        html = html.replace(f'{marker}{index}END', f'<span data-equation="{index}"></span>')
    return html, equations


class Renderer:
    def __init__(self):
        from playwright.sync_api import sync_playwright
        self.runtime = sync_playwright().start()
        try:
            self.browser = self.runtime.chromium.launch(headless=True)
            self.page = self.browser.new_page(viewport={'width': 640, 'height': 800},
                                              device_scale_factor=1)
            # No model text, links, macros or assets can contact the network.
            self.page.route('**/*', lambda route: route.abort())
            self.page.set_content('''<!doctype html><meta charset="utf-8">
              <style>
              * {box-sizing:border-box} body {margin:0;background:white;color:#17283c;
              font:16px/1.5 "Segoe UI",Arial,sans-serif} #message {padding:6px 10px;
              overflow-wrap:anywhere} p {margin:6px 0} h1,h2,h3 {line-height:1.3}
              pre {white-space:pre-wrap;background:#f0f3f7;padding:10px}
              code {font-family:Consolas,monospace} table {border-collapse:collapse}
              td,th {border:1px solid #ccd3dc;padding:5px} a {color:#1664a0}
              mjx-container {max-width:none} mjx-assistive-mml {display:none!important}
              .math-error {color:#9a291a;
              white-space:pre-wrap;border:1px solid #d99;padding:6px}
              </style><div id="message"></div>''')
            self.page.evaluate(r'''() => { window.MathJax = {
              loader: {load: []}, startup: {typeset: false},
              options: {enableMenu:false, enableAssistiveMml:false},
              tex: {packages: ['base','ams','newcommand'],
                    maxBuffer: 65536, maxMacros: 1000}, svg: {fontCache:'none'}
            }; }''')
            self.page.add_script_tag(path=str(BASE / 'vendor' / 'tex-svg-full.js'))
            self.page.evaluate('() => MathJax.startup.promise')
        except Exception:
            self.close()
            raise

    def render(self, text, width=580):
        html, equations = prepare(text)
        self.page.set_viewport_size({'width': max(280, min(width, 1800)), 'height': 800})
        errors = self.page.evaluate(r'''async ({html,equations}) => {
          MathJax.texReset();
          const target = document.getElementById('message');
          target.innerHTML = html;
          const errors = [];
          for (const span of target.querySelectorAll('[data-equation]')) {
            const eq = equations[Number(span.dataset.equation)];
            try {
              const node = await MathJax.tex2svgPromise(eq.tex, {display:eq.display});
              if (node.querySelector('[data-mml-node="merror"]') ||
                  node.querySelector('[data-mjx-error]')) throw Error('Unsupported or invalid TeX');
              span.replaceWith(node);
            } catch (error) {
              errors.push(String(error));
              span.className='math-error';
              span.textContent='Math could not render: ' + eq.source;
            }
          }
          return errors;
        }''', {'html': html, 'equations': equations})
        self.page.evaluate('async () => { await document.fonts.ready; await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame); }')
        # Capture all overflow, including wide matrices; never shrink an entire
        # long response to a tiny thumbnail. Tk provides horizontal scrolling.
        size = self.page.evaluate('''() => ({width:Math.max(innerWidth,document.body.scrollWidth),
                         height:Math.max(1,Math.ceil(document.getElementById('message').getBoundingClientRect().height))})''')
        if (size['width'] > 16000 or size['height'] > 100000
                or size['width'] * size['height'] > 40000000):
            raise ValueError('Response is too large to render; copy the original response.')
        png = self.page.screenshot(full_page=True, animations='disabled')
        with Image.open(io.BytesIO(png)) as source:
            # Keep each Text-widget image line short enough to scroll comfortably.
            images = [source.crop((0, y, source.width, min(y+160, size['height']))).convert('RGB')
                      for y in range(0, size['height'], 160)]
        return images, errors

    def close(self):
        if hasattr(self, 'browser'):
            self.browser.close()
        self.runtime.stop()


class RenderWorker:
    """One persistent browser, FIFO tasks, and no Tk calls outside the UI thread."""
    def __init__(self, jobs):
        self.jobs, self.tasks = jobs, queue.Queue()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def submit(self, text, width, callback):
        self.tasks.put((text, width, callback))

    def close(self):
        self.tasks.put(None)
        self.thread.join(timeout=5)

    def run(self):
        renderer = None
        try:
            while True:
                task = self.tasks.get()
                if task is None:
                    return
                text, width, callback = task
                try:
                    if renderer is None:
                        renderer = Renderer()
                    images, errors = renderer.render(text, width)
                    result = (images, errors, None)
                except Exception as exc:
                    result = ([], [], str(exc))
                    if renderer:
                        renderer.close()
                        renderer = None
                self.jobs.put(lambda cb=callback, result=result: cb(*result))
        finally:
            if renderer:
                renderer.close()
