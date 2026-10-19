"""Reproduce screenshot math spacing without regressing dollar-price handling."""
from pathlib import Path
import unittest
from hawkes_renderer import prepare, Renderer

SHARES=r'''## Step 1: Define Variables
Let:
- $ x $ = number of shares bought at $1.25 *per share*
- $ y $ = number of shares bought at $1.50 *per share*
---
## Step 2: Write the System of Equations
We are given two key pieces of information:
1. **Total shares purchased:** $ x + y = 600 $
2. **Total cost:** $ 1.25x + 1.50y = 825 $
This gives us the system:
$$\begin{cases}x+y=600 & \text{(Equation 1)}\\1.25x+1.50y=825 & \text{(Equation 2)}\end{cases}$$
---
## Step 3: Solve the System
We use **substitution** (or elimination) to solve for $ x $ and $ y $.
'''

class SpacedMathTests(unittest.TestCase):
    def test_spaces_prices_and_mixed_inline_math(self):
        cases=[('$ x $',1),('$x $',1),('$ x$',1),('$ 1.25x + 1.50y = 825 $',1),
          ('$ 2 $',1),('$ 2 + 2 = 4 $',1),('$5 and $10',0),('$5–$10',0),
          ('$153.60. Use $ x $ and $ y $.',2),('$5 **each**, then $ x $.',1),
          ('$5 a pound. Use $ x $.',1),('$ 5 and $ 10',0),('$ 5 per share; $ x $.',1),
          ('$5 sin(x)$',1),('$ 5 x + 2 $',1),('$153.60$',1),
          ('$153.60.\n\n$150.70.',0),(r'\$5 and \$10. Use $ x $.',1),
          ('`$ x $`\n```text\n$ y $\n```',0),('$ $',0),
          (r'$ \text{cost} = \$5 $',1)]
        for text,count in cases:
            with self.subTest(text=text):
                html,equations=prepare(text)
                self.assertEqual(len(equations),count)
        html,equations=prepare(SHARES)
        self.assertEqual(len(equations),7)
        self.assertIn('$1.25',html)
        self.assertIn('$1.50',html)
        self.assertIn('<em>per share</em>',html)
        self.assertEqual(equations[0]['tex'],'x')

    def test_screenshot_example_renders(self):
        renderer=Renderer()
        try:
            images,errors=renderer.render(SHARES,640)
            self.assertFalse(errors)
            self.assertEqual(renderer.page.locator('mjx-container').count(),7)
            text=renderer.page.locator('#message').inner_text()
            self.assertIn('$1.25',text)
            self.assertIn('$1.50',text)
            self.assertNotIn('$ x $',text)
            self.assertNotIn('$ 1.25x',text)
            renderer.page.screenshot(path=str(Path(__file__).parent/'spaced_math_verified.png'),full_page=True)
        finally:renderer.close()

if __name__=='__main__':unittest.main(verbosity=2)
