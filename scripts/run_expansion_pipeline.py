"""Resume only complete frozen stages; run resources -> tuning lock -> dev -> validation."""
from datetime import datetime,timezone
import json
import subprocess
import sys
import time

from gsearch.expansion_data import DATA,ROOT,QUOTAS,save,read
from gsearch.catalog_audit import digest

def main() -> None:
    from collections import Counter
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--wait-source',action='store_true');a=p.parse_args()
    last_complete_hash=None
    while True:
        try:state=read(DATA/'acquisition-state.json')
        except ValueError:
            time.sleep(.1);continue
        counts=Counter(r['cohort'] for r in state['accepted'])
        if counts==Counter(QUOTAS):
            current=digest(DATA/'acquisition-state.json')
            if current==last_complete_hash:break
            last_complete_hash=current
        elif not a.wait_source or time.time()-(DATA/'acquisition-state.json').stat().st_mtime>180:
            raise ValueError('Source acquisition incomplete or checkpoint stalled; preserve data before pipeline')
        print(json.dumps({'stage':'waiting-source','counts':dict(counts),'quota_completion_stable':last_complete_hash is not None}),flush=True)
        time.sleep(20)
    logs=DATA/'logs';logs.mkdir(parents=True,exist_ok=True)
    def run(name: str,args: list[str],path: object|None=None) -> None:
        save(logs/'pipeline-progress.json',{'stage':name,'status':'running','at':datetime.now(timezone.utc).isoformat()})
        print(json.dumps({'stage':name,'status':'running'}),flush=True)
        target=path or logs/(name+'.log')
        with target.open('w',encoding='utf-8') as log:
            result=subprocess.run([sys.executable,'-u',*args],stdout=log,stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:
            save(logs/'pipeline-progress.json',{'stage':name,'status':'failed','exit_code':result.returncode,'log':str(target)})
            raise RuntimeError('Stage failed; preserved log: '+str(target))
        print(json.dumps({'stage':name,'status':'complete'}),flush=True)
    if not (DATA/'documents.json').exists():run('freeze-corpus',['-m','gsearch.expansion_data','--phase','finalize'])
    if not (ROOT/'corpus-source-validation.json').exists():
        from scripts.validate_expansion import validate_corpus
        save(ROOT/'corpus-source-validation.json',validate_corpus())
    if not (ROOT/'resource-gates.json').exists():run('resource-gates',['-m','scripts.expansion_resources'])
    run('tests',['-m','unittest','discover','-s','tests','-v'],ROOT/'tests-final.log')
    if not (ROOT/'evaluation-plan.json').exists():run('freeze-evaluation',['-m','gsearch.benchmark_expansion','--phase','plan'])
    for n in (1000,5000,10000):
        names=('popular','sar','content','hybrid_a000','hybrid_a025','hybrid_a050','hybrid_a075','hybrid_a100')
        if not all((ROOT/f'{n}-{m}-tuning.json').exists() for m in names):
            run(f'tuning-{n}',['-m','gsearch.benchmark_expansion','--phase','tuning','--tier',str(n)])
    if not (ROOT/'locked-before-dev.json').exists():run('freeze-selection',['-m','gsearch.benchmark_expansion','--phase','lock'])
    for n in (1000,5000,10000):
        if not all((ROOT/f'{n}-{m}-dev.json').exists() for m in ('popular','sar','content','hybrid')):
            run(f'dev-{n}',['-m','gsearch.benchmark_expansion','--phase','dev','--tier',str(n)])
    run('final-report',['-m','scripts.make_stage13_report'],ROOT/'report-validation.log')
    save(logs/'pipeline-progress.json',{'stage':'all','status':'complete','at':datetime.now(timezone.utc).isoformat(),
                                      'final_validation_sha256':digest(ROOT/'final-validation.json')})

if __name__=='__main__':main()
