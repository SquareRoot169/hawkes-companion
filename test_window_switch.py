"""Regression: switching views must not retain incompatible place geometry."""
import tkinter as tk
import unittest
from unittest.mock import patch
from hawk_shell import HawkShell, screen_bounds
from Hawkes_AI_Companion import Companion

class WindowSwitchTests(unittest.TestCase):
    def test_return_from_rectangular_maximized_and_fit_views(self):
        root=tk.Tk()
        shell=HawkShell(root,start_mode='hawk')
        with patch.object(Companion,'refresh'):app=Companion(root,surface=shell.content)
        app.hawk_shell=shell;shell.on_close=app.close;shell.start();root.update()
        try:
            app.history=[{'role':'user','content':'preserve this'}]
            app.entry.insert('1.0','preserve the draft')
            hawk_geometry=root.geometry()
            self.check_bounds(shell)
            for _ in range(3):
                shell.toggle_mode();root.update()
                self.assertEqual(shell.mode,'compact')
                self.check_bounds(shell)
                self.assertEqual(shell.bar.winfo_y(),0)
                self.assertEqual(shell.content.winfo_width(),root.winfo_width())
                root.state('zoomed');root.update()
                self.check_bounds(shell)
                shell.toggle_mode();root.update()
                self.assertEqual(shell.mode,'hawk')
                self.assertEqual(root.state(),'normal')
                self.check_bounds(shell)
                self.assertEqual(root.geometry(),hawk_geometry)
                self.assertEqual(shell.content.winfo_width(),screen_bounds(root.winfo_width(),root.winfo_height())[2])
                shell.toggle_fit();root.update()
                self.assertTrue(shell.fit)
                self.check_bounds(shell)
                shell.toggle_mode();root.update()
                self.assertEqual(shell.mode,'compact')
                self.assertFalse(shell.fit)
                self.check_bounds(shell)
                root.attributes('-fullscreen',True);root.update()
                shell.toggle_mode();root.update()
                self.assertEqual(shell.mode,'hawk')
                self.assertFalse(root.attributes('-fullscreen'))
                self.check_bounds(shell)
            shell.toggle_fit();root.update()
            shell.exit_expanded();root.update()
            self.assertFalse(shell.fit)
            self.assertEqual(root.geometry(),hawk_geometry)
            self.assertEqual(app.history[0]['content'],'preserve this')
            self.assertEqual(app.entry.get('1.0','end').strip(),'preserve the draft')
        finally:app.close()

    def check_bounds(self,shell):
        root=shell.root
        for widget in (shell.bar,shell.bar_buttons[0],shell.content):
            self.assertTrue(widget.winfo_ismapped())
            x=widget.winfo_rootx()-root.winfo_rootx()
            y=widget.winfo_rooty()-root.winfo_rooty()
            with self.subTest(mode=shell.mode,widget=str(widget)):
                self.assertGreaterEqual(x,0)
                self.assertGreaterEqual(y,0)
                self.assertLessEqual(x+widget.winfo_width(),root.winfo_width())
                self.assertLessEqual(y+widget.winfo_height(),root.winfo_height())

if __name__=='__main__':unittest.main(verbosity=2)
