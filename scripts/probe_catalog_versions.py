"""One bounded official explicit-version probe with original arxiv.py transport/parser."""
from datetime import datetime,timezone
import json
from pathlib import Path
import time

from gsearch.catalog_audit import CACHE,DATA,REPORT,digest,read,stamp

def main() -> None:
    output=DATA/'official-version-probe.json'
    if output.exists():
        raise ValueError('Official probe already recorded; do not repeat')
    from gsearch import metadata_fetch as mf
    from filelock import FileLock
    for limit in (mf.ROOT/'rate-limit.json',CACHE/'rate-limit.json'):
        if limit.exists() and stamp(read(limit)['retry_not_before'])>datetime.now(timezone.utc):
            output.parent.mkdir(parents=True,exist_ok=True)
            output.write_text(json.dumps({'attempted':False,'reason':'existing official API cooldown','cooldown_file':str(limit)}),encoding='utf-8')
            return
    samples=read(DATA/'sample-plan.json')['samples']
    chosen={}
    for row in samples:
        chosen.setdefault(row['stratum'],row['paper_id'])
    requested=[d+'v1' for _,d in sorted(chosen.items())]
    package=mf.upstream()
    # Existing code is reused unchanged; only transport cache destination is process-local.
    mf.ROOT=CACHE
    session=mf.RecordedSession('arxiv',3.1)
    client=package.Client(page_size=100,delay_seconds=3.1,num_retries=0)
    client._session=session
    results,error=[],None
    started=time.perf_counter()
    with FileLock(str(CACHE/'official-global.lock')):
        try:
            results=[mf.record_api(r,session.receipts[-1]) for r in client.results(package.Search(id_list=requested,max_results=len(requested)))]
        except Exception as exc:
            error=type(exc).__name__+': '+str(exc)
    receipt={'attempted':True,'requested_ids':requested,'records':results,'error':error,
             'seconds':time.perf_counter()-started,'requests':session.receipts,'retries':0,
             'sample_plan_sha256':digest(DATA/'sample-plan.json'),'note':'one explicit-v1 batch; stop on429, no alternate arxiv host; submitted date still not observed historical ingest time'}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps({'attempted':True,'records':len(results),'seconds':receipt['seconds'],'error':error,'statuses':[r['status'] for r in session.receipts]}),flush=True)

if __name__=='__main__':
    main()
