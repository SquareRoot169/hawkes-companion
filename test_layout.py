import sys,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import tkinter as tk
from PIL import ImageGrab
from Hawkes_AI_Companion import Companion
from hawkes_renderer import Renderer
class LayoutTests(unittest.TestCase):
 def test_compact_render(self):
  r=Renderer()
  try:
   images,errors=r.render('A short answer: $x=2$.',580)
   self.assertFalse(errors)
   self.assertLess(sum(i.height for i in images),120)
  finally:r.close()
 def test_compact_controls_fit(self):
  from tkinter import ttk
  from PIL import Image
  for scaling in (1.33,2.0):
   root=tk.Tk()
   root.tk.call('tk','scaling',scaling)
   with patch.object(Companion,'refresh'):app=Companion(root)
   try:
    root.attributes('-topmost',False)
    for size in ('560x600','620x660','700x780'):
     root.geometry(size)
     app.set_image(Image.new('RGB',(400,200)),'Attached image')
     root.update()
     widgets=[]
     def visit(parent):
      for child in parent.winfo_children():
       if isinstance(child,ttk.Button):widgets.append(child)
       visit(child)
     visit(root)
     for widget in widgets+[app.entry,app.models]:
      with self.subTest(scaling=scaling,size=size,control=str(widget)):
       self.assertTrue(widget.winfo_ismapped())
       x=widget.winfo_rootx()-root.winfo_rootx()
       y=widget.winfo_rooty()-root.winfo_rooty()
       self.assertGreaterEqual(x,0)
       self.assertGreaterEqual(y,0)
       self.assertLessEqual(x+widget.winfo_width(),root.winfo_width())
       self.assertLessEqual(y+widget.winfo_height(),root.winfo_height())
       if isinstance(widget,ttk.Button):
        self.assertGreaterEqual(widget.winfo_width(),widget.winfo_reqwidth())
     self.assertGreater(app.chat.winfo_height(),40)
     app.remove_image()
   finally:app.close()
 def test_scroll_resize_and_vision(self):
  root=tk.Tk()
  with patch.object(Companion,'refresh'):app=Companion(root)
  root.attributes('-topmost',False)
  def pump():
   end=time.time()+15
   while time.time()<end:
    root.update()
    if not app.chat.get('1.0','end').count('Formatting response') and not app.resize_job:
     # allow worker rerenders to finish
     for _ in range(20):root.update();time.sleep(.03)
     return
    time.sleep(.03)
   self.fail('Rendering timed out')
  pump()
  app.add('user','Please explain how to solve this equation.')
  app.add('assistant','## Solve with confidence\n**Subtract 3** from both sides.\n\n$$2x+3=7 \\quad \\Rightarrow \\quad x=2$$\n\n'+('A useful explanation of the next step.\n\n'*65))
  pump()
  record=app.rendered_messages[-1]
  self.assertIsNotNone(app.chat.dlineinfo(record['heading']))
  self.assertFalse(app.horizontal.winfo_manager())
  image_count=len(app.chat.image_names())
  root.geometry('640x780');root.update();time.sleep(.4);pump();time.sleep(.5);root.update()
  self.assertLess(len(app.chat.image_names()),image_count*2)
  self.assertEqual(len(app.chat.image_names()), sum(len(r['photos']) for r in app.rendered_messages))
  self.assertFalse(app.horizontal.winfo_manager())
  # Return to start of answer for the preview.
  app.chat.yview(record['heading']);root.update()
  payloads=[]
  app.api=lambda endpoint,payload=None:(payloads.append(payload) or {'message':{'content':'The result is $4$.'}})
  app.model.set('qwen3:8b')
  app.history=[{'role':'user','content':'image','images':['test-image']}]
  app.entry.insert('1.0','Explain this again')
  app.send()
  while app.busy:root.update();time.sleep(.03)
  self.assertEqual(payloads[-1]['model'],'qwen3-vl:8b')
  app.close()
if __name__=='__main__':unittest.main(verbosity=2)
