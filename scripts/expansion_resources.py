"""Sequential isolated fits with native Windows peaks and parent resource limits."""
import argparse
from datetime import datetime,timezone
from pathlib import Path
import subprocess
import sys
import time

import psutil

from gsearch.expansion_data import DATA,ROOT,save,read

def main() -> None:
    p=argparse.ArgumentParser();p.add_argument('--child-tier',type=int,choices=(1000,5000,10000))
    args=p.parse_args()
    if args.child_tier:
        from gsearch.content_recommendation import sklearn_runtime
        sklearn_runtime()
        from threadpoolctl import threadpool_limits
        from gsearch.expansion_recommendation import load,signature
        started=time.perf_counter();proc=psutil.Process()
        baseline=proc.memory_info()._asdict()
        with threadpool_limits(limits=1):
            model=load(args.child_tier)
            fit_wall=time.perf_counter()-started
            fit_memory=proc.memory_info()._asdict()
            sig=signature(model)
            # Exercise actual source-version reading as well as the fitted recommend path.
            user=model.users[0];at=read(ROOT/'admission-plan.json')['end']
            hits=model.recommend(user,at,'hybrid',10,.5)
            original=model.read(hits[0]['doc_id'],at)
        memory=proc.memory_info()._asdict()
        save(ROOT/f'resource-{args.child_tier}.json',{'tier':args.child_tier,'fit_wall_seconds':fit_wall,
            'total_with_verification_seconds':time.perf_counter()-started,'fit':model.fit,'baseline_memory_bytes':baseline,
            'native_memory_at_fit_end':fit_memory,'fit_phase_peak_working_set_bytes':fit_memory.get('peak_wset',fit_memory['rss']),
            'fit_phase_peak_commit_counter_bytes':fit_memory.get('peak_pagefile',fit_memory['vms']),'final_native_memory_bytes':memory,
            'peak_working_set_bytes':memory.get('peak_wset',memory['rss']),
            'peak_commit_counter_bytes':memory.get('peak_pagefile',memory['vms']),
            'model_signature':sig,'source_read_verified':original['source_verified'],
            'native_peak_note':'Windows PROCESS_MEMORY_COUNTERS via original psutil; whole-process lifetime peaks incl imports/fit temporaries, no fake sampled-only peak',
            'finished_at':datetime.now(timezone.utc).isoformat()})
        return
    plan=read(ROOT/'admission-plan.json');limits=plan['resource_limits']
    if not (DATA/'documents.json').exists():raise ValueError('Version corpus must be frozen first')
    if not (ROOT/'corpus-source-validation.json').exists():raise ValueError('Full source/version admission proof must precede resource fits')
    summary=[]
    for n in (1000,5000,10000):
        result=ROOT/f'resource-{n}.json';gate=ROOT/f'resource-{n}-gate.json'
        if gate.exists():
            previous=read(gate)
            if not previous['passed']:raise ValueError('Earlier resource gate failed; do not silently rerun larger tiers')
            summary.append(previous);continue
        if result.exists():raise ValueError('Unpaired resource output exists; inspect before restart')
        with (ROOT/f'resource-{n}.log').open('w',encoding='utf-8') as log:
            child=subprocess.Popen([sys.executable,'-u','-m','scripts.expansion_resources','--child-tier',str(n)],
                stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            watched=psutil.Process(child.pid);started=time.perf_counter();reason=None;peak_rss=0;peak_commit=0
            while child.poll() is None:
                try:
                    m=watched.memory_info();peak_rss=max(peak_rss,getattr(m,'peak_wset',m.rss));peak_commit=max(peak_commit,getattr(m,'peak_pagefile',m.vms))
                    if peak_rss>limits['peak_working_set_gib']*2**30:reason='native peak working-set limit'
                    elif peak_commit>limits['peak_private_commit_gib']*2**30:reason='native peak commit-counter limit'
                    elif time.perf_counter()-started>limits['fit_timeout_seconds']:reason='fit timeout'
                    if reason:
                        child.terminate();child.wait(timeout=10);break
                except psutil.NoSuchProcess:break
                time.sleep(.05)
            code=child.wait()
        passed=code==0 and reason is None and result.exists()
        r={'tier':n,'passed':passed,'exit_code':code,'stop_reason':reason,'parent_observed_peak_wset':peak_rss,
           'parent_observed_peak_commit':peak_commit,'wall_seconds':time.perf_counter()-started,'limits':limits,
           'available_memory_before_next_gib':psutil.virtual_memory().available/2**30}
        if passed:
            actual=read(result)
            passed=actual['peak_working_set_bytes']<=limits['peak_working_set_gib']*2**30 and actual['peak_commit_counter_bytes']<=limits['peak_private_commit_gib']*2**30
            r['passed']=passed
        save(gate,r);summary.append(r);print(__import__('json').dumps(r),flush=True)
        if not passed:raise RuntimeError('Resource gate failed; preserve outputs and do not advance')
    save(ROOT/'resource-gates.json',summary)

if __name__=='__main__':
    main()
