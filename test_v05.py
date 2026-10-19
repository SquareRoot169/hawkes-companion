"""Speech off/on, cancellation, buffering, speech text and optional beak animation."""
import queue
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch
import numpy as np
from hawkes_speech import SpeechWorker, spoken_text, chunks
from Hawkes_AI_Companion import Companion
from hawk_shell import HawkShell


def pump(jobs,until,timeout=4):
    end=time.time()+timeout
    while time.time()<end:
        try:
            while True:jobs.get_nowait()()
        except queue.Empty:pass
        if until():return
        time.sleep(.01)
    raise AssertionError('Timed out')


class SpeechTests(unittest.TestCase):
    def test_spoken_math_currency_and_markdown(self):
        text=spoken_text(r'## Step 1'+ '\n' +r'**Solve** $2x+3=7$. Use $x=\frac{3}{2}$. Materials cost $153.60 and $5.5.')
        self.assertNotIn('\\',text)
        self.assertNotIn('**',text)
        self.assertIn('equals',text)
        self.assertIn('fraction 3 over 2 end fraction',text)
        self.assertIn('153 dollars and 60 cents',text)
        self.assertIn('5 dollars and 50 cents',text)
        self.assertIn('displayed matrix',spoken_text(r'$$\begin{bmatrix}1&2\\3&4\end{bmatrix}$$'))
        self.assertGreater(len(chunks('A useful sentence with a clear stopping point. '*50)),2)
        self.assertTrue(all(0<len(c)<=450 for c in chunks('A useful sentence. '*80)))

    def test_lazy_engine_and_stop_discards_pending_audio(self):
        jobs=queue.Queue();events=[];loads=[];started=threading.Event()
        class Engine:
            def create(self,*args):return np.ones(2400,dtype=np.float32)*.1,24000
        def factory():loads.append(1);return Engine()
        def play(samples,rate,cancel,worker):
            worker.level=.7;started.set();cancel.wait(2)
        worker=SpeechWorker(jobs,lambda *args:events.append(args),factory,play)
        try:
            self.assertIsNone(worker.thread)
            self.assertEqual(loads,[])
            worker.speak('A test sentence for optional voice output.')
            self.assertTrue(started.wait(2))
            worker.stop()
            pump(jobs,lambda:not worker.playing)
            self.assertEqual(worker.level,0)
            # Stale queued UI events cannot make the stopped voice appear active.
            self.assertEqual(events,[])
            self.assertEqual(loads,[1])
            with patch('hawkes_speech.spoken_text',side_effect=ValueError('bad formula')):
                worker.speak('malformed input')
            pump(jobs,lambda:bool(events))
            self.assertEqual(events[-1][0],'error')
        finally:worker.close()

    def test_prefetch_reuse_and_error_recovery(self):
        jobs=queue.Queue();events=[];loads=[];created=[];overlap=[]
        class Engine:
            def create(self,text,*args):
                created.append(text);return np.zeros(2400,dtype=np.float32),24000
        def factory():loads.append(1);return Engine()
        def player(samples,rate,cancel,worker):
            count=len(created);time.sleep(.08);overlap.append(len(created)>count)
        worker=SpeechWorker(jobs,lambda state,detail:events.append(state),factory,player)
        try:
            worker.speak('Here is a longer explanation with complete sentences. '*25)
            pump(jobs,lambda:'idle' in events)
            self.assertGreater(len(created),1)
            self.assertTrue(any(overlap))
            events.clear();worker.speak('Read one more short explanation.')
            pump(jobs,lambda:'idle' in events)
            self.assertEqual(loads,[1])
            events.clear()
            def fail(*args):raise RuntimeError('Audio device unavailable')
            worker.player=fail
            worker.speak('Device failure must not break the chat.')
            pump(jobs,lambda:'error' in events)
        finally:worker.close()

    def test_compact_default_voice_controls_and_beak(self):
        root=tk.Tk()
        root.tk.call('tk','scaling',2.0)
        shell=HawkShell(root,start_mode='compact')
        with patch.object(Companion,'refresh'):
            app=Companion(root,surface=shell.content)
        app.hawk_shell=shell;shell.on_close=app.close;shell.start();root.update()
        root.geometry('560x600');root.update()
        try:
            self.assertEqual(shell.mode,'compact')
            self.assertEqual(root.winfo_height(),600)
            self.assertGreater(app.chat.winfo_height(),40)
            self.assertFalse(app.voice_enabled.get())
            self.assertIsNone(app.speech.thread)
            self.assertEqual(str(app.read_button['state']),'disabled')
            with patch.object(app.speech,'speak') as say:
                app.voice_enabled.set(True);app.toggle_voice()
                app.latest_reply='A test reply';app.read_reply()
                self.assertTrue(say.called)
                app.voice_enabled.set(False);app.toggle_voice()
                say.reset_mock();app.read_reply();self.assertFalse(say.called)
            shell.set_speech_level(.8)
            self.assertTrue(shell.mouth_open)
            self.assertEqual(str(shell.canvas.itemcget(shell.mouth_item,'state')),'normal')
            app.toggle_voice()
            self.assertFalse(shell.mouth_open)
            app.history=[{'role':'user','content':'keep'}]
            shell.toggle_mode();root.update()
            self.assertEqual(shell.mode,'hawk')
            self.assertEqual(app.history[0]['content'],'keep')
        finally:app.close()

if __name__=='__main__':unittest.main(verbosity=2)
