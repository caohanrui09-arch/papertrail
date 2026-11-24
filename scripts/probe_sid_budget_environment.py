"""Inspect installed metadata only; do not import GPU/web packages or modify them."""
from importlib.metadata import distributions
from pathlib import Path
import re

from gsearch.quality_protocol import save
from gsearch.sid_budget import ROOT, read


def main() -> None:
    target=ROOT/'environment-validation.json'
    if target.exists(): raise FileExistsError('Preserve environment observation')
    roots={'cpu':Path('.cache/stage17/runtime/Lib/site-packages'),
           'gpu':Path('../.venv/Lib/site-packages'),
           'web':Path('.cache/stage39/runtime-secure/Lib/site-packages')}
    norm=lambda name:re.sub(r'[-_.]+','-',name).lower()
    result={}
    for kind,path in roots.items():
        assert path.is_dir(),path
        actual={norm(d.metadata['Name']):d.version for d in distributions(path=[str(path)])}
        expected={norm(r['name']):r['version'] for r in read(Path('reports/stage45')/(kind+'-packages-after.json'))}
        assert actual==expected,kind
        result[kind]={'count':len(actual),'unchanged_from_stage45':True,'packages':actual}
    save(target,{'status':'passed','method':'stdlib metadata read only; no package imports/install', 'environments':result})
    print({'status':'passed','counts':{k:v['count'] for k,v in result.items()}},flush=True)


if __name__=='__main__':main()
