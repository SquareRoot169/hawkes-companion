"""Factorial inline mathematics must not be mistaken for dollar prices."""
import unittest
import pypdfium2 as pdfium
from hawkes_renderer import prepare,Renderer
from hawkes_latex import PdfOptions,document,compile_document

EXAMPLE=r'''### Step 2: Simplify the Binomial Coefficient
1. Compute $5! = 5 \times 4 \times 3 \times 2 \times 1 = 120$
2. Compute $3! = 3 \times 2 \times 1 = 6$
3. Compute $(5-3)! = 2! = 2 \times 1 = 2$

$$\binom{5}{3}=\frac{5!}{3!\,2!}=10$$

### Final Answer
$$\boxed{10}$$
'''

class FactorialTests(unittest.TestCase):
    def test_factorials_and_price_exclamations_are_distinct(self):
        cases=[(EXAMPLE,5),(r'$5!$',1),(r'$ 5 ! $',1),
               (r'$5!\times4$',1),(r'$5! + 3! = 126$',1),
               ('Only $5! Great savings.',0),('Just $5! Then solve $x=2$.',1),
               ('Pay $5! And $10!',0),('`$5! = 120$`',0),
               (r'\$5! Use $x=2$.',1)]
        for text,count in cases:
            with self.subTest(text=text):self.assertEqual(len(prepare(text)[1]),count)
    def test_real_latex_pdf_has_factorials_and_boxed_final_answer(self):
        source=document(EXAMPLE,PdfOptions())
        self.assertNotIn(r'Compute \$5!',source)
        self.assertNotIn(r'\textbackslash{}times',source)
        data=compile_document(source)
        with pdfium.PdfDocument(data) as pdf:
            text=''.join(page.get_textpage().get_text_range() for page in pdf)
            self.assertNotIn('$',text);self.assertNotIn(r'\times',text)
            self.assertIn('120',text);self.assertIn('Final Answer',text)
            self.assertTrue(text.count('10')>=2)
    def test_chat_mathjax_also_renders_factorial_steps(self):
        renderer=Renderer()
        try:
            _,errors=renderer.render(EXAMPLE,640)
            self.assertFalse(errors)
            self.assertEqual(renderer.page.locator('mjx-container').count(),5)
            self.assertNotIn(r'\times',renderer.page.locator('#message').inner_text())
        finally:renderer.close()

if __name__=='__main__':unittest.main(verbosity=2)
