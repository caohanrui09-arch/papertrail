"""Create a monochrome presentation copy; preserve layout, alpha and luminance."""
from pathlib import Path
import hashlib,json,re,shutil
ROOT=Path(__file__).resolve().parents[1]

def gray(r,g,b):
    def linear(c):
        c=c/255
        return c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4
    value=.2126*linear(r)+.7152*linear(g)+.0722*linear(b)
    return round(255*(12.92*value if value<=.0031308 else 1.055*value**(1/2.4)-.055))

def neutral(text):
    def hexcolor(m):
        v=m[1]
        if len(v) in (3,4):v=''.join(c*2 for c in v)
        n=gray(*(int(v[i:i+2],16) for i in (0,2,4)))
        return '#'+f'{n:02x}'*3+v[6:]
    text=re.sub(r'#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![\w-])',hexcolor,text)
    def rgbcolor(m):
        value=gray(*(int(m[i]) for i in (2,3,4)))
        return m[1]+'('+f'{value},{value},{value}'+(m[5] or '')+')'
    return re.sub(r'\b(rgb|rgba)\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(,[^)]*)?\)',rgbcolor,text)

def main():
    new=ROOT/'deploy/stage66'
    if new.exists():raise ValueError('Preserve existing delivery')
    shutil.copytree(ROOT/'deploy/stage61',new,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    files=[]
    for path in (new/'web').rglob('*'):
        if not path.is_file() or 'vendor' in path.parts or path.suffix not in ('.css','.svg','.html','.mjs'):continue
        old=path.read_text(encoding='utf8');value=neutral(old)
        if path.suffix=='.html':
            value=value.replace('</head>','<link rel="stylesheet" href="/monochrome.css?v=66.1"></head>')
            value=re.sub(r'((?:href|src)="/[^"?]+\.(?:css|svg|mjs))(?:\?[^"\s]*)?("?)',lambda m:m[1]+'?v=66.1'+m[2],value)
        elif path.suffix=='.mjs':
            value=re.sub(r"(from\s+['\"]\./[^'\"?]+\.mjs)(?:\?[^'\"]*)?(['\"])",lambda m:m[1]+'?v=66.1'+m[2],value)
            value=value.replace('src="/mark.svg"','src="/mark.svg?v=66.1"')
        if value!=old:path.write_text(value,encoding='utf8');files.append(str(path.relative_to(new)))
    for name in ['run_research61_local.py','research61_control.py']:
        value=(ROOT/'scripts'/name).read_text().replace('stage61','stage66').replace('research61','research66').replace('Start v61','Start v66')
        (ROOT/'scripts'/name.replace('61','66')).write_text(value,encoding='utf8')
    path=new/'trialsite/delivery.py';path.write_text(path.read_text().replace("'release':'stage61'","'release':'stage66'"),encoding='utf8')
    lab=ROOT/'research66'
    for name in ['lab.html','lab.js']:
        value=neutral((ROOT/'research63'/name).read_text(encoding='utf8'))
        if name.endswith('.html'):value=value.replace('</style>','</style><link rel="stylesheet" href="/monochrome.css">')
        (lab/name).write_text(value,encoding='utf8')
    value=(ROOT/'research63/server.py').read_text().replace("ROOT/'research63/lab.html'","ROOT/'research66/lab.html'").replace("ROOT/'research63/lab.js'","ROOT/'research66/lab.js'")
    value=value.replace("    @app.get('/lab.js')","    @app.get('/monochrome.css')\n    def theme():return FileResponse(ROOT/'deploy/stage66/web/monochrome.css',media_type='text/css')\n    @app.get('/lab.js')")
    (lab/'server.py').write_text(value,encoding='utf8')
    value=(ROOT/'research63/control.py').read_text().replace("research63.server","research66.server").replace(".cache/stage63'",".cache/stage66-lab'")
    (lab/'control.py').write_text(value,encoding='utf8')
    report=ROOT/'reports/stage66';report.mkdir(exist_ok=True)
    (report/'theme-build.json').write_text(json.dumps({'changed_presentation_files':files,'base':'stage61','algorithm_changes':False,'method':'neutralize color literals preserving relative luminance and alpha; explicit neutral focus/primary controls'},indent=2),encoding='utf8')

if __name__=='__main__':main()
