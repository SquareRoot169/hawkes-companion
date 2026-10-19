"""Optional offline neural narration. No microphone and no cloud speech calls."""
from pathlib import Path
from html import escape
from html.parser import HTMLParser
import math
import queue
import re
import threading
import time
import numpy as np

BASE = Path(__file__).resolve().parent
VOICES = {'Heart (female)': 'af_heart', 'Michael (male)': 'am_michael'}
PREVIEW = ('Let us take this one step at a time. An equation is like a balanced scale. '
           'Whatever you do to one side, do to the other. Subtract three from both sides, '
           'then divide by two. Now you can see why the answer makes sense.')


def _group(text, pos):
    while pos < len(text) and text[pos].isspace():pos += 1
    if pos >= len(text) or text[pos] != '{':return None, pos
    start, depth = pos + 1, 1
    pos += 1
    while pos < len(text):
        if text[pos] == '\\':pos += 2;continue
        if text[pos] == '{':depth += 1
        elif text[pos] == '}':
            depth -= 1
            if not depth:return text[start:pos], pos + 1
        pos += 1
    return None, start - 1


def math_to_speech(tex):
    # Complex layouts are visually authoritative; do not flatten matrices into
    # ambiguous strings of numbers or read formatting commands aloud.
    if re.search(r'\\begin\{(?:[bp]?matrix|cases|array)',tex):
        return ' See the displayed matrix or system of equations. '
    from pylatexenc.latex2text import LatexNodes2Text
    parts, pos = [], 0
    pattern = re.compile(r'\\(?:dfrac|tfrac|frac)\b')
    while match := pattern.search(tex,pos):
        parts.append(tex[pos:match.start()])
        a,end = _group(tex,match.end())
        b,finish = _group(tex,end)
        if a is None or b is None:
            parts.append(tex[match.start():match.end()]);pos=match.end();continue
        parts.append(' fraction '+math_to_speech(a)+' over '+math_to_speech(b)+' end fraction ')
        pos=finish
    parts.append(tex[pos:])
    value=LatexNodes2Text().latex_to_text(''.join(parts))
    value=re.sub(r'\^\s*\{?2\}?\b',' squared ',value)
    value=re.sub(r'\^\s*\{?3\}?\b',' cubed ',value)
    value=value.replace('^',' to the power of ').replace('_',' sub ')
    for symbol,word in [('≤',' less than or equal to '),('≥',' greater than or equal to '),
                         ('≠',' is not equal to '),('±',' plus or minus '),('√',' square root of '),
                         ('⇒',' therefore '),('→',' gives '),('×',' times '),('÷',' divided by '),
                         ('π',' pi '),('α',' alpha '),('β',' beta '),('θ',' theta '),('∫',' integral '),('∑',' sum '),('∞',' infinity '),('=',' equals '),('+',' plus '),
                         ('−',' minus '),('-',' minus '),('/',' divided by '),('<',' less than '),
                         ('>',' greater than ')]:value=value.replace(symbol,word)
    return re.sub(r'\s+',' ',value).strip()


class _Text(HTMLParser):
    def __init__(self):super().__init__();self.parts=[]
    def handle_data(self,data):self.parts.append(data)
    def handle_starttag(self,tag,attrs):
        if tag in ('p','li','h1','h2','h3','h4','h5','h6','br','tr','pre'):self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('p','li','h1','h2','h3','h4','h5','h6','tr','pre'):self.parts.append('\n')


def spoken_text(markdown):
    from hawkes_renderer import prepare
    html,equations=prepare(markdown)
    for i,eq in enumerate(equations):
        html=html.replace(f'<span data-equation="{i}"></span>',escape(math_to_speech(eq['tex'])))
    parser=_Text();parser.feed(html)
    text=''.join(parser.parts)
    def money(match):
        whole=match[1].replace(',','')
        decimal=match[2] or ''
        if len(decimal)>2:return whole+' point '+' '.join(decimal)+' dollars'
        cents=int(decimal.ljust(2,'0')) if decimal else 0
        return whole+' dollars'+(' and '+str(cents)+' cents' if cents else '')
    text=re.sub(r'\$(\d[\d,]*)(?:\.(\d+))?',money,text)
    text=re.sub('[✅✓✔]',' Check. ',text)
    text=re.sub(r'[^\S\n]+',' ',text)
    return re.sub(r'\n+','\n',text).strip()


def chunks(text,limit=450):
    # Short batches reduce time to first speech and allow cancellation between
    # model calls. Prefer a complete sentence over arbitrary word boundaries.
    sentences=re.split(r'(?<=[.!?])\s+|\n+',text)
    result=[];current=''
    for sentence in sentences:
        for word in sentence.split():
            if len(current)+len(word)+1 > limit:
                result.append(current);current=''
            current += (' ' if current else '')+word
        if len(current)>160 and current.endswith(('.', '?','!')):
            result.append(current);current=''
    if current:result.append(current)
    return result


class NeuralVoice:
    def __init__(self):
        import onnxruntime as rt
        from kokoro_onnx import Kokoro
        rt.disable_telemetry_events()
        options=rt.SessionOptions()
        options.intra_op_num_threads=2
        options.inter_op_num_threads=1
        session=rt.InferenceSession(str(BASE/'voice/kokoro-v1.0.onnx'),
                 sess_options=options,providers=['CPUExecutionProvider'])
        self.engine=Kokoro.from_session(session,str(BASE/'voice/voices-v1.0.bin'))

    def create(self,text,voice,speed):
        samples,rate=self.engine.create(text,voice=voice,speed=speed,lang='en-us')
        return np.asarray(samples,dtype=np.float32),rate


class SpeechWorker:
    def __init__(self,jobs,on_state,engine_factory=NeuralVoice,player=None):
        self.jobs,self.on_state=jobs,on_state
        self.engine_factory=engine_factory
        self.player=player
        self.engine=None
        self.tasks=queue.Queue(maxsize=1)
        self.token=0
        self.cancel=threading.Event()
        self.closed=False
        self.level=0.0
        self.playing=False
        self.thread=None  # Voice OFF does not import/load the neural model.

    def _emit(self,token,state,detail=''):
        def deliver():
            if not self.closed and token==self.token:self.on_state(state,detail)
        self.jobs.put(deliver)

    def stop(self):
        self.token+=1
        self.cancel.set()
        self.level=0.0
        self.playing=False
        while True:
            try:self.tasks.get_nowait()
            except queue.Empty:break

    def speak(self,text,voice='af_heart',speed=1.0):
        self.stop()
        if self.closed:return
        try:text=spoken_text(text)
        except Exception as exc:
            self._emit(self.token,'error','Could not prepare speech: '+str(exc));return
        if not text:return
        self.cancel=threading.Event()
        task=(self.token,self.cancel,text,voice,float(speed))
        self.tasks.put_nowait(task)
        if self.thread is None:
            self.thread=threading.Thread(target=self.run,daemon=True)
            self.thread.start()

    def run(self):
        while not self.closed:
            try:task=self.tasks.get(timeout=.1)
            except queue.Empty:continue
            token,cancel,text,voice,speed=task
            if cancel.is_set():continue
            try:
                self._emit(token,'preparing','Preparing local voice…')
                if self.engine is None:self.engine=self.engine_factory()
                audio_queue=queue.Queue(maxsize=1)
                def offer(item):
                    while not cancel.is_set() and not self.closed:
                        try:audio_queue.put(item,timeout=.05);return
                        except queue.Full:pass
                def produce():
                    try:
                        for section in chunks(text):
                            if cancel.is_set() or self.closed:return
                            samples,rate=self.engine.create(section,voice,speed)
                            if cancel.is_set():return
                            offer((samples,rate))
                    except Exception as exc:offer(exc)
                    finally:offer(None)
                producer=threading.Thread(target=produce,daemon=True)
                producer.start()
                try:
                    while not cancel.is_set() and not self.closed:
                        try:item=audio_queue.get(timeout=.05)
                        except queue.Empty:continue
                        if item is None:break
                        if isinstance(item,Exception):raise item
                        samples,rate=item
                        self._emit(token,'speaking','Speaking locally')
                        self.playing=True
                        if self.player:self.player(samples,rate,cancel,self)
                        else:self.play(samples,rate,cancel)
                        self.playing=False
                        self.level=0.0
                finally:
                    # One synthesis producer at a time. A cancelled inference
                    # finishes quietly; it can never play its stale result.
                    if not producer.is_alive():producer.join()
                    else:
                        # On a playback failure, cancel before joining so a
                        # producer waiting on its bounded queue can exit.
                        import sys
                        if sys.exc_info()[0] is not None:cancel.set()
                        while producer.is_alive() and not self.closed:
                            producer.join(timeout=.05)
                if not cancel.is_set():self._emit(token,'idle','Voice ready')
            except Exception as exc:
                if token==self.token and not self.closed:self._emit(token,'error',str(exc))
            finally:
                self.level=0.0
                self.playing=False

    def play(self,samples,rate,cancel):
        import sounddevice as sd
        position=0
        def callback(outdata,frames,timing,status):
            nonlocal position
            outdata.fill(0)
            if cancel.is_set():raise sd.CallbackAbort
            count=min(frames,len(samples)-position)
            if count:
                block=samples[position:position+count]
                outdata[:count,0]=block
                # Follow live output blocks rather than synthesis progress.
                rms=float(np.sqrt(np.mean(block*block)))
                self.level=min(1.0,rms*9)
                position+=count
            if position>=len(samples):raise sd.CallbackStop
        with sd.OutputStream(samplerate=rate,channels=1,dtype='float32',
                             blocksize=max(256,int(rate*.04)),latency='low',callback=callback) as stream:
            while stream.active:
                if cancel.wait(.02):
                    stream.abort();break
        self.level=0.0

    def close(self):
        self.closed=True
        self.stop()
        if self.thread:self.thread.join(timeout=2)
