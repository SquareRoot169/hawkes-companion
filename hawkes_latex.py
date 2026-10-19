"""Controlled Markdown -> LaTeX typesetting. No model-supplied document commands."""
from dataclasses import dataclass, asdict
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
import os
import re
import subprocess
import tempfile
import threading
import queue
import json

from hawkes_renderer import prepare
from hawkes_pdf import export_directory, write_pdf

BASE = Path(__file__).resolve().parent
TEMPLATES = ('Classic mathematics', 'Lecture notes', 'Compact handout')
ACCENTS = {'Black': '000000', 'Navy': '18344D', 'Teal': '176A65'}

@dataclass(frozen=True)
class PdfOptions:
    title: str = 'Mathematics notes'
    author: str = ''
    date: str = date.today().strftime('%B %d, %Y')
    filename: str = 'Hawkes Notes'
    template: str = TEMPLATES[0]
    size: int = 11
    margins: str = 'Standard'
    paper: str = 'Letter'
    accent: str = 'Black'
    numbers: bool = False
    pages: bool = True
    graphs: bool = False
    caption: str = 'Graph of the selected functions'

    def validate(self):
        if self.template not in TEMPLATES or self.accent not in ACCENTS:
            raise ValueError('Choose one of the available document styles.')
        if self.size not in (10,11,12) or self.margins not in ('Standard','Generous','Compact') or self.paper not in ('Letter','A4'):
            raise ValueError('Choose a supported text size, margin and paper size.')
        for key in ('title','author','date','filename','caption'):
            if len(getattr(self,key))>200:raise ValueError('Document fields must be 200 characters or fewer.')
        return self

def load_options():
    try:
        raw=json.loads((BASE/'pdf_preferences.json').read_text(encoding='utf-8'))
        saved_day=raw.pop('_saved_day',None)
        if raw.get('date')==saved_day:raw['date']=PdfOptions().date
        return PdfOptions(**raw).validate()
    except (OSError,ValueError,TypeError):return PdfOptions()

def save_options(options):
    try:
        path=BASE/'pdf_preferences.json'
        temporary=path.with_suffix('.tmp')
        raw=asdict(options);raw['_saved_day']=PdfOptions().date
        temporary.write_text(json.dumps(raw,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(temporary,path)
    except OSError:pass  # Read-only portable installations still export normally.

SPECIAL={'\\':r'\textbackslash{}','{':r'\{','}':r'\}','$':r'\$','&':r'\&',
         '#':r'\#','%':r'\%','_':r'\_','~':r'\textasciitilde{}','^':r'\textasciicircum{}'}
SYMBOLS={'✅':r'\ensuremath{\checkmark}', '✓':r'\ensuremath{\checkmark}',
         '❌':r'\ensuremath{\times}', '×':r'\ensuremath{\times}', '÷':r'\ensuremath{\div}',
         '→':r'\ensuremath{\rightarrow}', '⇒':r'\ensuremath{\Rightarrow}',
         '≤':r'\ensuremath{\leq}', '≥':r'\ensuremath{\geq}', '≠':r'\ensuremath{\neq}',
         '∞':r'\ensuremath{\infty}', 'π':r'\ensuremath{\pi}', '√':r'\ensuremath{\surd}',
         '−':'-', '–':'--', '—':'---', '’':"'", '‘':"'", '“':'``','”':"''", '…':r'\ldots{}',
         '\ufe0f':'', '\u200b':'', '\u00a0':'~'}

def escape(text):
    result=[]
    for char in text:
        if char in SYMBOLS:result.append(SYMBOLS[char])
        elif char in SPECIAL:result.append(SPECIAL[char])
        elif char in '\n\t\r' or ' '<=char<='\u024f':result.append(char)
        else:raise ValueError('A character in this response cannot be typeset yet: '+repr(char)+'. Your chat answer is unchanged.')
    return ''.join(result)

# Deliberately a mathematical vocabulary, not a general TeX programming language.
COMMANDS=set('''frac dfrac tfrac cfrac binom dbinom tbinom sqrt root of over atop choose
left right middle big Big bigg Bigg bigl bigr Bigl Bigr biggl biggr Biggl Biggr
begin end text textrm textbf textit textnormal mathrm mathbf mathit mathsf mathtt mathcal mathbb mathfrak boldsymbol
operatorname boxed fbox overset underset overbrace underbrace overline underline widehat widetilde hat bar vec dot ddot tilde
sum prod int iint iiint oint lim limsup liminf sup inf min max sin cos tan cot sec csc arcsin arccos arctan sinh cosh tanh log ln exp det gcd Pr
alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa lambda mu nu xi pi varpi rho varrho sigma varsigma tau upsilon phi varphi chi psi omega
Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega
infty partial nabla ell hbar imath jmath Re Im angle triangle square checkmark
times cdot div pm mp ast star circ bullet degree percent
le leq ge geq ne neq approx sim simeq equiv cong propto ll gg lesssim gtrsim
in notin ni subset subseteq supset supseteq cup cap setminus emptyset varnothing forall exists neg land lor lnot
to gets mapsto rightarrow leftarrow leftrightarrow Rightarrow Leftarrow Leftrightarrow implies iff longrightarrow longleftarrow Longrightarrow Longleftrightarrow
quad qquad enspace thinspace medspace thickspace hspace vspace spacing
ldots cdots vdots ddots dots lbrace rbrace langle rangle lvert rvert lVert rVert vert Vert
displaystyle textstyle scriptstyle scriptscriptstyle limits nolimits nonumber notag tag label ref
substack mod bmod pmod perp parallel mid colon not phantom vphantom hphantom smash
color textcolor cancel bcanceled bcancel xcancel mathop mathrel mathbin mathord mathopen mathclose punctuation
'''.split())
# No colors/macros/labels from content: these belong to the controlled template.
COMMANDS -= {'color','textcolor','label','ref','vspace','spacing','bcanceled'}
ENVIRONMENTS={'aligned','alignedat','gathered','cases','matrix','pmatrix','bmatrix','Bmatrix','vmatrix','Vmatrix','smallmatrix','split','align','align*','gather','gather*','equation','equation*'}

def safe_math(tex):
    tex=tex.strip()
    if len(tex)>8000 or re.search(r'(?<!\\)[%#$]|\^\^|[\x00-\x08\x0b-\x1f]',tex):
        raise ValueError('An equation contains unsupported TeX. Ask for standard mathematical notation and try again.')
    # Explicitly reject all commands outside the known mathematical vocabulary.
    for command in re.findall(r'\\([A-Za-z]+|[^A-Za-z])',tex):
        if command.isalpha() and command not in COMMANDS:raise ValueError('Unsupported math command: \\'+command+'. Your chat answer is unchanged.')
        if not command.isalpha() and command not in '\\{}|,;:!_%#$&^~ \n\t\r':raise ValueError('An equation contains an unsupported control symbol.')
    for env in re.findall(r'\\(?:begin|end)\s*\{([^}]+)\}',tex):
        if env not in ENVIRONMENTS:raise ValueError('Unsupported mathematical environment: '+env)
    # Do not allow arbitrary control symbols to change parsing/category codes.
    depth=0
    for m in re.finditer(r'\\.|[{}]',tex):
        if m[0]=='{':depth+=1
        elif m[0]=='}':depth-=1
        if depth<0:raise ValueError('An equation has unmatched braces.')
    if depth:raise ValueError('An equation has unmatched braces.')
    # Top-level environments must be nested inside our numbered/unnumbered wrapper.
    tex=re.sub(r'\\(begin|end)\{align\*?\}',r'\\\1{aligned}',tex)
    tex=re.sub(r'\\(begin|end)\{gather\*?\}',r'\\\1{gathered}',tex)
    tex=re.sub(r'\\(?:begin|end)\{equation\*?\}','',tex)
    for symbol,macro in {'−':'-','×':r'\times ','÷':r'\div ','≤':r'\leq ','≥':r'\geq ','≠':r'\neq ','π':r'\pi ','∞':r'\infty '}.items():tex=tex.replace(symbol,macro)
    return tex

class Node:
    def __init__(self,tag='',attrs=None):self.tag=tag;self.attrs=dict(attrs or []);self.children=[]

class Tree(HTMLParser):
    def __init__(self,html):
        super().__init__(convert_charrefs=True);self.root=Node();self.stack=[self.root];self.feed(html)
    def handle_starttag(self,tag,attrs):
        node=Node(tag,attrs);self.stack[-1].children.append(node)
        if tag not in ('br','hr','img'):self.stack.append(node)
    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,0,-1):
            if self.stack[i].tag==tag:self.stack=self.stack[:i];break
    def handle_data(self,data):self.stack[-1].children.append(data)

class Converter:
    def __init__(self,equations,options):self.equations=equations;self.options=options
    def contents(self,node):return ''.join(self.render(c) for c in node.children)
    def render(self,node):
        if isinstance(node,str):return escape(node)
        tag=node.tag
        if tag=='span' and 'data-equation' in node.attrs:
            eq=self.equations[int(node.attrs['data-equation'])];tex=safe_math(eq['tex'])
            if not eq['display']:return r'\('+tex+r'\)'
            env='equation' if self.options.numbers else 'equation*'
            return '\n\\begin{'+env+'}\n'+tex+'\n\\end{'+env+'}\n'
        body=self.contents(node)
        if tag in ('h1','h2','h3','h4','h5','h6'):
            command={'h1':'section','h2':'section','h3':'subsection'}.get(tag,'subsubsection')
            return '\n\\'+command+'*{'+body.strip()+'}\n'
        if tag=='p':return '\n'+body.strip()+'\n\n'
        if tag in ('strong','b'):return r'\textbf{'+body+'}'
        if tag in ('em','i'):return r'\emph{'+body+'}'
        if tag in ('ul','ol'):
            env='itemize' if tag=='ul' else 'enumerate'
            start=node.attrs.get('start','1')
            setting='[start='+start+']' if tag=='ol' and start.isdigit() else ''
            return '\n\\begin{'+env+'}'+setting+'\n'+body+'\n\\end{'+env+'}\n'
        if tag=='li':return '\n\\item '+body.strip()+'\n'
        if tag=='br':return '\n'  # prose wraps naturally, math linebreaks stay untouched.
        if tag=='hr':
            if self.options.template=='Classic mathematics':return '\n'
            return '\n\\par\\smallskip\\noindent\\textcolor{accent!25}{\\rule{\\linewidth}{0.3pt}}\\par\\smallskip\n'
        if tag=='blockquote':return '\n\\begin{quote}'+body+'\\end{quote}\n'
        if tag=='pre':return '\n\\begin{quote}\\small\\ttfamily '+body+'\\end{quote}\n'
        if tag=='code':return r'\texttt{'+body+'}'
        if tag=='a':return body # Keep visible label. Never follow links or inject raw hrefs.
        if tag=='img':return r'\emph{[Image: '+escape(node.attrs.get('alt','not included'))+']}'
        if tag=='table':
            rows=[]
            def find(n):
                if isinstance(n,str):return
                if n.tag=='tr':rows.append(n)
                else:
                    for c in n.children:find(c)
            find(node)
            cols=max((len([c for c in r.children if isinstance(c,Node) and c.tag in ('td','th')]) for r in rows),default=1)
            if cols>6:raise ValueError('This table is too wide. Please use six columns or fewer for a readable PDF.')
            col='p{\\dimexpr(\\linewidth-'+str((cols-1)*12)+'pt)/'+str(cols)+'\\relax}'
            spec='@{}'+col*cols+'@{}'
            out='\n\\begin{longtable}{'+spec+'}\n\\toprule\n'
            for row in rows:
                cells=[c for c in row.children if isinstance(c,Node) and c.tag in ('td','th')]
                out+=' & '.join((r'\textbf{'+self.contents(c).strip()+'}') if c.tag=='th' else self.contents(c).strip() for c in cells)+r' \\'+'\n'
                if any(c.tag=='th' for c in cells):out+='\\midrule\n'
            return out+'\\bottomrule\n\\end{longtable}\n'
        return body

def document(text,options,graph=False):
    options.validate()
    text=re.sub(r'[\ufffd\s]+$','',text)
    if not text.strip():raise ValueError('There is no completed tutor answer to export.')
    if len(text)>100000:raise ValueError('This answer is too long for a single export. Please split it into parts.')
    html,equations=prepare(text)
    tree=Tree(html).root;converter=Converter(equations,options)
    # Keep short worked steps together; long sections remain freely breakable.
    groups=[]
    for child in tree.children:
        if isinstance(child,Node) and child.tag.startswith('h') and child.tag!='hr':groups.append([])
        if not groups:groups.append([])
        groups[-1].append(child)
    chunks=[]
    for group in groups:
        block=Node();block.children=group
        rendered=converter.contents(block)
        def measure(node):
            if isinstance(node,str):return (len(node.strip()),0,False)
            if node.tag=='span' and 'data-equation' in node.attrs:
                eq=equations[int(node.attrs['data-equation'])]
                return (len(eq['tex']),int(eq['display']),False)
            values=[measure(c) for c in node.children]
            return (sum(v[0] for v in values),sum(v[1] for v in values),node.tag=='table' or any(v[2] for v in values))
        length,displays,table=measure(block)
        if length<1100 and displays<7 and not table:
            rendered='\n\\par\\addvspace{0.7em}\\noindent\\begin{minipage}{\\linewidth}\n'+rendered+'\n\\end{minipage}\\par\n'
        chunks.append(rendered)
    body=''.join(chunks)
    margin={'Standard':'1in','Generous':'1.2in','Compact':'0.7in'}[options.margins]
    header=''
    if options.title.strip():header+=r'{\LARGE\bfseries\color{accent} '+escape(options.title.strip())+r'\par}'+'\n'
    meta=[escape(s.strip()) for s in (options.author,options.date) if s.strip()]
    if meta:header+=r'\vspace{0.5em}{\small '+r'\quad\textperiodcentered\quad '.join(meta)+r'\par}'+'\n'
    if header:header+=r'\vspace{0.8em}'+'\n'
    classic=options.template=='Classic mathematics'
    heading_style=r'\normalfont\large\bfseries' if classic else r'\sffamily\large\bfseries'
    small_heading=r'\normalfont\normalsize\bfseries' if classic else r'\sffamily\normalsize\bfseries'
    minor_heading=r'\normalfont\normalsize\itshape' if classic else r'\sffamily\normalsize\itshape'
    spacing='1.00' if options.template=='Compact handout' else '1.06'
    preamble=r'''\documentclass[SIZEpt,PAPERpaper]{article}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage{amsmath,amssymb,mathtools,cancel}
\usepackage[margin=MARGIN,headheight=15pt]{geometry}
\usepackage{xcolor,graphicx,enumitem,booktabs,longtable,titlesec,fancyhdr}
\usepackage[unicode,hidelinks]{hyperref}
\definecolor{accent}{HTML}{ACCENT}
\titleformat{\section}{HEADING\color{accent}}{}{0pt}{}
\titleformat{\subsection}{SMALLHEADING\color{accent}}{}{0pt}{}
\titleformat{\subsubsection}{MINORHEADING\color{accent}}{}{0pt}{}
\titlespacing*{\section}{0pt}{1.3em}{0.5em}
\titlespacing*{\subsection}{0pt}{1em}{0.4em}
\setlength{\parindent}{0pt}
\setlength{\parskip}{0.3em}
\linespread{SPACING}
\setlist{topsep=0.3em,itemsep=0.25em,parsep=0.1em,leftmargin=*}
\setlength{\emergencystretch}{2em}
\allowdisplaybreaks[1]
\widowpenalty=10000\clubpenalty=10000
\raggedbottom
\pagestyle{fancy}\fancyhf{}
\renewcommand{\headrulewidth}{0pt}
\renewcommand{\footrulewidth}{0pt}
PAGEFOOT
\hypersetup{pdftitle={TITLE},pdfauthor={AUTHOR},pdfcreator={Hawkes Companion v0.7 / LaTeX}}
\begin{document}
'''
    for key,value in {'SIZE':str(options.size),'PAPER':'letter' if options.paper=='Letter' else 'a4','MARGIN':margin,
                      'ACCENT':ACCENTS[options.accent],'SMALLHEADING':small_heading,'MINORHEADING':minor_heading,
                      'HEADING':heading_style,'SPACING':spacing,
                      'PAGEFOOT':r'\fancyfoot[C]{\small\thepage}' if options.pages else '',
                      'TITLE':escape(options.title),'AUTHOR':escape(options.author)}.items():preamble=preamble.replace(key,value)
    if options.graphs and graph:
        body+='\n\\section*{Graph}\n\\begin{center}\n\\includegraphics[width=0.92\\linewidth,height=0.45\\textheight,keepaspectratio]{graph.pdf}\n\\par\\small '+escape(options.caption)+'\n\\end{center}\n'
    return preamble+header+body+'\n\\end{document}\n'

def compiler_environment():
    env=os.environ.copy()
    env['TECTONIC_CACHE_DIR']=str(BASE/'tex'/'cache')
    env['TECTONIC_UNTRUSTED_MODE']='1'
    return env

def compile_document(source,graph=None,online=False):
    engine=BASE/'tex'/'tectonic.exe'
    if not engine.is_file():raise RuntimeError('The bundled LaTeX engine is missing. Please restore the complete v0.7 folder.')
    with tempfile.TemporaryDirectory(prefix='hawkes-latex-') as directory:
        folder=Path(directory);(folder/'notes.tex').write_text(source,encoding='utf-8')
        if graph:(folder/'graph.pdf').write_bytes(graph)
        command=[str(engine),'-X','compile','--untrusted','--keep-logs']
        if not online:command+=['--only-cached']
        command+=['notes.tex']
        try:
            result=subprocess.run(command,cwd=folder,env=compiler_environment(),capture_output=True,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=120)
        except subprocess.TimeoutExpired:raise RuntimeError('Typesetting took too long. Your answer is unchanged; try a shorter response.')
        log=(folder/'notes.log').read_text(encoding='utf-8',errors='replace') if (folder/'notes.log').exists() else ''
        details=(result.stdout+result.stderr).decode('utf-8',errors='replace')
        if result.returncode or not (folder/'notes.pdf').is_file():
            match=re.search(r'^(?:error:|!)([^\n]+)',details+'\n'+log,re.M)
            reason=match[1].strip() if match else 'The equation or document could not be compiled.'
            raise ValueError('LaTeX could not typeset this response. '+reason[:240]+' Your chat answer is unchanged.')
        if 'Missing character:' in log:raise ValueError('A character is unavailable in the mathematics font. Your answer is unchanged; no incomplete PDF was saved.')
        overflow=[float(x) for x in re.findall(r'Overfull \\hbox \(([\d.]+)pt too wide\)',log)]
        if overflow and max(overflow)>8:raise ValueError('An equation or line is too wide for these margins. Try smaller text or Compact margins, or ask for shorter aligned equations.')
        if any(float(x)>8 for x in re.findall(r'Overfull \\vbox \(([\d.]+)pt too high\)',log)):
            raise ValueError('A section is too tall for the page. Ask for shorter steps or try Compact margins.')
        return (folder/'notes.pdf').read_bytes()

def save_document(data,options,folder=None):
    name=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',options.filename).strip(' .')[:100] or 'Hawkes Notes'
    if name.lower().endswith('.pdf'):name=name[:-4]
    if name.upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:name='Notes_'+name
    # Existing exclusive, atomic save implementation also handles duplicate names.
    path=write_pdf(data,folder or export_directory(),stem=name)
    return path

def save_latex_source(text,options,graph=None,folder=None):
    """Export a complete, editable document and its local graph as one folder."""
    options.validate()
    if options.graphs and not graph:raise ValueError('Select a graph before exporting LaTeX, or turn off Include a graph.')
    source=document(text,options,bool(graph))
    name=re.sub(r'[^\w .-]','_',options.filename,flags=re.UNICODE).strip(' .')[:90] or 'Hawkes Notes'
    if name.lower().endswith(('.pdf','.tex')):name=name[:-4].strip(' .') or 'Hawkes Notes'
    name+=' LaTeX'
    folder=Path(folder) if folder is not None else export_directory()
    folder.mkdir(parents=True,exist_ok=True)
    for index in range(10000):
        target=folder/(name+('' if index==0 else f'_{index+1}'))
        try:target.mkdir()
        except FileExistsError:continue
        break
    else:raise OSError('Too many exports have the same name. Please choose a different filename.')
    created=[]
    try:
        files={'README.txt':('HAWKES COMPANION v0.7 - LaTeX SOURCE\n\n'
            'main.tex is a complete UTF-8 LaTeX document, including its preamble.\n'
            'It uses the response and PDF Studio settings present at export.\n'
            'Compile with a standard LaTeX installation containing the listed packages.\n'
            'The companion uses Tectonic (XeTeX); no online editor is required.\n'
            'For Overleaf, upload main.tex and select XeLaTeX for matching output.\n'
            'If graph.pdf is present, keep it beside main.tex and share both files.\n'
            'The graph is a snapshot of the selected plot.\n'
            'This export does not contain the AI model, voice files or chat history.\n').encode('utf-8')}
        if options.graphs:files['graph.pdf']=graph
        files['main.tex']=source.encode('utf-8')
        for filename,data in files.items():
            path=target/filename;created.append(path);path.write_bytes(data)
        return target/'main.tex'
    except Exception:
        # Only our exclusively reserved folder and files can be cleaned up.
        for path in created:path.unlink(missing_ok=True)
        target.rmdir()
        raise

class LatexWorker:
    def __init__(self,jobs):self.jobs=jobs;self.tasks=queue.Queue(maxsize=1);self.thread=None;self.closed=False
    def submit(self,text,options,graph,callback):
        if self.closed:raise RuntimeError('The companion is closing.')
        self.tasks.put_nowait((str(text),options,graph,callback))
        if self.thread is None:self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
    def run(self):
        while not self.closed:
            try:text,options,graph,callback=self.tasks.get(timeout=.2)
            except queue.Empty:continue
            try:data=compile_document(document(text,options,bool(graph)),graph if options.graphs else None);result=(data,None)
            except Exception as exc:result=(None,str(exc))
            if not self.closed:self.jobs.put(lambda cb=callback,res=result:cb(*res))
    def close(self):self.closed=True
