"""One-time local resource setup; normal app use remains offline."""
from pathlib import Path
import argparse,hashlib,json,os,sys,tempfile,urllib.request,zipfile

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))

def digest(path):
    result=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):result.update(chunk)
    return result.hexdigest()

def download(url,path,expected):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and digest(path)==expected:return
    temporary=path.with_suffix(path.suffix+'.download')
    try:
        print('Downloading '+path.name+'…',flush=True)
        urllib.request.urlretrieve(url,temporary)
        if digest(temporary)!=expected:raise ValueError('Checksum mismatch for '+path.name)
        os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)

def prepare_latex():
    if os.name!='nt':raise RuntimeError('This setup script targets 64-bit Windows.')
    metadata=json.loads((BASE/'tex/PROVENANCE.json').read_text())
    engine=BASE/'tex/tectonic.exe'
    if not engine.exists() or digest(engine)!=metadata['exe_sha256']:
        with tempfile.TemporaryDirectory() as directory:
            archive=Path(directory)/'tectonic.zip'
            download(metadata['url'],archive,metadata['archive_sha256'])
            with zipfile.ZipFile(archive) as z:
                data=z.read('tectonic.exe')
            if hashlib.sha256(data).hexdigest()!=metadata['exe_sha256']:raise ValueError('Unexpected engine checksum.')
            engine.write_bytes(data)
    from hawkes_latex import PdfOptions,document,compile_document
    from test_v06 import SAMPLE_RESPONSE
    print('Preparing LaTeX fonts and packages for offline use…',flush=True)
    probe=[]
    for size in ('tiny','scriptsize','footnotesize','small','normalsize','large','Large','LARGE','huge','Huge'):
        for family in ('rmfamily','sffamily','ttfamily'):
            for style in ('mdseries','bfseries','itshape'):
                probe.append('{'+chr(92)+size+chr(92)+family+chr(92)+style+r' abc XYZ 123 \textbackslash{} \textasciitilde{} \textasciicircum{} \textperiodcentered{} \textcopyright{}\par}')
    probe.append(r'$\mathbb{R}_{\mathbb{Z}}+\mathfrak{g}+\boldsymbol{\alpha}+\mathsf{x}+\mathtt{y}+\mathcal{F}$')
    probe.append(r'\begin{longtable}{ll}\toprule Name&Value\\\midrule Test&1\\\bottomrule\end{longtable}')
    for size in (10,11,12):
        source=document(SAMPLE_RESPONSE,PdfOptions(size=size,template='Lecture notes'))
        source=source.replace(r'\end{document}','\n'.join(probe)+'\n'+r'\end{document}')
        compile_document(source,online=True)
        compile_document(source)
        print(str(size)+'-point resources verified offline.',flush=True)

def prepare_voice():
    hashes=json.loads((BASE/'ASSET_SHA256.json').read_text())
    root='https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/'
    for name in ('kokoro-v1.0.onnx','voices-v1.0.bin'):
        download(root+name,BASE/'voice'/name,hashes['voice/'+name])

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--voice',action='store_true',help='Download the optional offline voice model.')
    options=parser.parse_args()
    prepare_latex()
    if options.voice:prepare_voice()
    print('Local resources ready.',flush=True)

if __name__=='__main__':main()
