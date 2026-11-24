"""Explicit public allowlist: the user's workspace and visitor volume never enter the archive."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
BUNDLE=ROOT/'deploy/stage39'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    singles=['README.md','THIRD_PARTY_NOTICES.md','requirements.in','requirements.lock','render.yaml','reuse-receipt.json']
    paths=[BUNDLE/p for p in singles]
    for folder,extensions in [('trialsite',{'.py'}),('catalog',{'.json','.xml'}),('web',{'.html','.mjs','.js','.css','.svg','.txt','.md',''})]:
        paths += [p for p in (BUNDLE/folder).rglob('*') if p.is_file() and p.suffix in extensions and '__pycache__' not in p.parts]
    paths=sorted(paths)
    for p in paths:
        name=str(p.relative_to(BUNDLE)).replace('\\','/')
        if not p.resolve().is_relative_to(BUNDLE.resolve()) or any(x in name.lower() for x in ['.sqlite','session.key','.env','visitor-data','.cache']):
            raise ValueError('Non-public asset in allowlist')
    manifest={str(p.relative_to(BUNDLE)).replace('\\','/'):sha(p) for p in paths}
    dest=ROOT/'exports/stage39/papertrail-trial.zip'
    dest.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(dest,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as out:
        for p in paths:out.write(p,str(p.relative_to(BUNDLE)).replace('\\','/'))
    report={'files':manifest,'count':len(paths),'zip':str(dest.relative_to(ROOT)),'zip_sha256':sha(dest),
            'zip_bytes':dest.stat().st_size,'private_data_included':False,'published':False,
            'not_included':['visitor database','session.key','old 10000-paper interaction data','checkpoints','screenshots','workspace','Git history']}
    (ROOT/'reports/stage39/package.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print({k:v for k,v in report.items() if k!='files'})


if __name__=='__main__':main()
