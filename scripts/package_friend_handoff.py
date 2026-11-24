"""Explicit offline code/public-app allowlists; never archive private research data."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT=Path(__file__).resolve().parents[1]
HAND=ROOT/'handoff/2026-11-22'
OUT=ROOT/'exports/stage78'
REPORT=ROOT/'reports/stage78'

def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def tree(folder):
    return [p for p in folder.rglob('*') if p.is_file() and not p.is_symlink() and '__pycache__' not in p.parts
            and p.suffix not in ('.pyc','.whl') and p.name not in ('.lock','.gitignore')]

def archive(name,entries):
    entries=sorted(set(entries),key=lambda r:r[1]);manifest={}
    for path,target in entries:
        if path.is_symlink() or not path.absolute().is_relative_to(ROOT):raise ValueError('Outside source root')
        parts=Path(target).parts
        if target.startswith('/') or '..' in parts or parts[0] in ('data','runs','visitor-data','.git','.cache'):raise ValueError('Private or unsafe member '+target)
        if path.suffix in ('.sqlite','.sqlite3','.db','.log') or path.name in ('.env','session.key'):raise ValueError('Private asset '+target)
    dest=OUT/name
    with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as z:
        for i,(path,target) in enumerate(entries):
            manifest[target]={'sha256':digest(path),'bytes':path.stat().st_size}
            z.write(path,target)
            if i%1000==0:print(f'{name}: {i}/{len(entries)} files',flush=True)
        z.writestr('PACKAGE-MANIFEST.json',json.dumps({'files':manifest,'private_data_included':False},ensure_ascii=False,indent=2))
    return {'filename':name,'bytes':dest.stat().st_size,'sha256':digest(dest),'files':len(entries),'manifest':manifest}

def main():
    OUT.mkdir(parents=True,exist_ok=True);REPORT.mkdir(parents=True,exist_ok=True)
    # File names, hashes and sizes only; user-level data are intentionally not copied.
    replica=ROOT/'.cache/stage17/replica'
    assets=[p for p in tree(replica) if '.cache/stage11' not in p.as_posix() and p.suffix not in ('.dll','.pyd','.lib')]
    inventory={'scope':'dependency inventory only; no research payload',
        'files':{str(p.relative_to(ROOT)).replace('\\','/'):{'bytes':p.stat().st_size,'sha256':digest(p)} for p in assets}}
    (HAND/'native-asset-inventory.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding='utf8')
    source=[]
    allowed={'.py','.mjs','.js','.cjs','.css','.html','.svg','.json','.jsonl','.md','.txt','.in','.lock','.toml','.yaml','.yml','.cmd','.ps1','.xml','.atom','.csv','.ts','.tsx','.jsx','.png'}
    dirs=[ROOT/n for n in ('gsearch','scripts','tests','docs','third_party','web','handoff')]+list(ROOT.glob('research[0-9]*'))+[ROOT/'deploy/stage66']
    for folder in dirs:
        for p in tree(folder):
            if p.suffix in allowed or p.name.startswith('LICENSE'):source.append((p,p.relative_to(ROOT).as_posix()))
    for p in ROOT.iterdir():
        if p.is_file() and (p.suffix in ('.md','.txt','.in','.cmd','.toml') or p.name=='.gitignore'):source.append((p,p.relative_to(ROOT).as_posix()))
    evidence=list((ROOT/'reports').glob('stage*/final-validation.json'))
    evidence += [ROOT/n for n in ('reports/stage17/requirements-win-cpu.lock','reports/stage17/sklearn-target.lock','reports/stage17/bootstrap-source.json','reports/stage77/after-home.png','reports/stage77/after-agent.png')]
    source += [(p,p.relative_to(ROOT).as_posix()) for p in evidence if p.is_file()]
    # The preview uses the already-reviewed public bundle, not the original research API.
    preview=[]
    for folder in [ROOT/'deploy/stage66',ROOT/'handoff',ROOT/'research73',ROOT/'research75',ROOT/'research76',ROOT/'research77']:
        preview += [(p,p.relative_to(ROOT).as_posix()) for p in tree(folder) if p.suffix not in ('.cjs',) and p.name!='native-asset-inventory.json']
    for n in ('scripts/run_research73_workbench.py','scripts/run_research75_workbench.py','scripts/run_research76_workbench.py','scripts/run_research77_workbench.py','web/papertrail-v26/dist/vendor/jsoneditor.js','THIRD_PARTY_NOTICES.md'):
        p=ROOT/n;preview.append((p,n))
    preview.append((HAND/'START-PAPERTRAIL.cmd','START-PAPERTRAIL.cmd'))
    preview.append((HAND/'START_HERE.md','START_HERE.md'))
    python=ROOT/'.cache/stage39/python/cpython-3.12.16-windows-x86_64-none'
    deps=ROOT/'.cache/stage39/runtime-secure/Lib/site-packages'
    for folder,target in [(python,'runtime/python'),(deps,'runtime/deps')]:
        preview += [(p,target+'/'+p.relative_to(folder).as_posix()) for p in tree(folder) if not any(x in ('tests','test') for x in p.relative_to(folder).parts)]
    result={'date':'2026-11-22','source_stage':77,'platform':'Windows x64',
            'bundles':[archive('Papertrail-Windows-Preview.zip',preview),archive('Papertrail-Source-Handoff.zip',source)],
            'excluded':['all original data/','all runs/','original .cache/ and venvs','visitor state and keys','user-level research predictions and traces','model weights'],
            'native_agent_runtime_included':False,'new_machine_validated':False,'published_or_sent':False}
    (REPORT/'packages.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    public={**result,'bundles':[{k:v for k,v in b.items() if k!='manifest'} for b in result['bundles']]}
    (OUT/'PACKAGE-SUMMARY.json').write_text(json.dumps(public,ensure_ascii=False,indent=2),encoding='utf8')
    for name in ('START_HERE.md','NEXT_AGENT_PROMPT.md','FULL_AGENT_ASSETS.md'):(OUT/name).write_bytes((HAND/name).read_bytes())
    print(json.dumps(public,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
