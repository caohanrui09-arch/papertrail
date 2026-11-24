"""Targeted v1 candidate acquisition, reusing the pinned arxiv.py transport/parser."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'.cache/stage57/acquisition'
OUT=ROOT/'data/stage57-candidates'
DEFAULT_IDS=['2504.18458','2506.00806','2511.16670','2610.25999','2610.15810']

def save(path:Path,value:object)->None:
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def main()->None:
    import os
    os.chdir(ROOT)
    ap=argparse.ArgumentParser();ap.add_argument('--ids',nargs='*');ap.add_argument('--audit',type=Path)
    ap.add_argument('--acquire',action='store_true');ap.add_argument('--direct',action='store_true');args=ap.parse_args()
    from gsearch import metadata_fetch as mf
    from gsearch.paper_identity import arxiv_identity
    from filelock import FileLock
    ids=args.ids
    if args.audit:
        raw=args.audit.read_bytes()
        if len(raw)>256*1024:raise ValueError('Audit over256KiB')
        data=json.loads(raw)
        if data.get('format')!='papertrail-demand-audit' or data.get('schema_version')!=1:raise ValueError('Expected explicit demand audit export')
        ids=[r['expected_paper'] for r in data['items'] if r.get('expected_paper') and r.get('status')!='archived']
        if not ids:raise ValueError('No known target IDs: source discovery/relevance review is required; do not invent IDs')
    ids=ids if ids is not None else DEFAULT_IDS
    parsed=[arxiv_identity(d) for d in ids]
    if not 1<=len(parsed)<=10 or any('/' in d or v not in (None,1) for d,v in parsed):raise ValueError('1–10 modern IDs, explicit v1 only')
    ids=sorted({d for d,_ in parsed});fingerprint=hashlib.sha256(json.dumps(ids).encode()).hexdigest()[:16]
    destination=OUT/fingerprint;receipt_path=destination/'acquisition.json'
    if receipt_path.exists():
        existing=json.loads(receipt_path.read_text(encoding='utf-8'))
        print({'cached':True,'records':len(existing['records']),'error':existing['error'],'receipt':str(receipt_path.relative_to(ROOT))},flush=True);return
    if not args.acquire:
        print({'requested_ids':ids,'network':False,'next':'add --acquire after reviewing requested IDs'},flush=True);return
    for folder in [ROOT/'.cache/stage10',ROOT/'.cache/stage13',ROOT/'.cache/stage29',ROOT/'.cache/stage39/acquisition',CACHE]:
        path=folder/'rate-limit.json'
        if path.exists() and datetime.fromisoformat(json.loads(path.read_text())['retry_not_before'])>datetime.now(timezone.utc):raise ValueError('Official API cooldown; no alternate endpoint')
    api=mf.upstream();original_root=mf.ROOT;mf.ROOT=CACHE;CACHE.mkdir(parents=True,exist_ok=True)
    session=mf.RecordedSession('arxiv',3.1)
    if args.direct:session.trust_env=False
    client=api.Client(page_size=100,delay_seconds=3.1,num_retries=0);client._session=session
    rows=[];error=None
    try:
        with FileLock(str(CACHE/'acquisition.lock'),timeout=0):
            for result in client.results(api.Search(id_list=[d+'v1' for d in ids],max_results=len(ids))):
                row=mf.record_api(result,session.receipts[-1])
                if row['doc_id'] not in ids or row['version']!=1 or not row['title'].strip() or not row['abstract'].strip():raise ValueError('Wrong identity/version or empty original metadata')
                raw=Path(row['provenance']['raw_path'])
                if hashlib.sha256(raw.read_bytes()).hexdigest()!=row['provenance']['raw_sha256']:raise ValueError('Raw response hash changed')
                rows.append(row|{'categories':list(result.categories),'primary_category':result.primary_category,'version_key':'arxiv:'+row['doc_id']+'v1'})
    except Exception as exc:error=type(exc).__name__+': '+str(exc)
    finally:
        session.close();mf.ROOT=original_root
    if len({r['doc_id'] for r in rows})!=len(rows):raise ValueError('Duplicate source result')
    missing=sorted(set(ids)-{r['doc_id'] for r in rows})
    receipt={'request_ids':ids,'records':rows,'missing_ids':missing,'error':error,'requests':session.receipts,
        'source':'existing pinned arxiv.py Client + RecordedSession + original v1 Result parser',
        'scope':'candidate acquisition, not automatic relevance labels or historical admission','created_at':datetime.now(timezone.utc).isoformat()}
    save(receipt_path,receipt)
    print({'records':len(rows),'missing':missing,'error':error,'receipt':str(receipt_path.relative_to(ROOT))},flush=True)
    if error or missing:raise SystemExit(1)
if __name__=='__main__':main()
