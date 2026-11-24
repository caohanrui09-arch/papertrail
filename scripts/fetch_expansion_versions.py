"""Original arxiv.py v1 acquisition, source/train-only quotas, globally paced and resumable."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import time

from gsearch.expansion_data import CACHE,DATA,ROOT,DOMAINS,QUOTAS,available_at,save
from gsearch.catalog_audit import read,digest,stamp

def main() -> None:
    p=argparse.ArgumentParser();p.add_argument('--max-batches',type=int);p.add_argument('--probe',action='store_true')
    p.add_argument('--direct',action='store_true',help='Session-only direct route if configured local proxy is unavailable; TLS/pacing/cooldown unchanged')
    args=p.parse_args()
    from gsearch import metadata_fetch as mf
    from filelock import FileLock
    plan=read(ROOT/'admission-plan.json');pool=read(DATA/'pool.json')
    scope=read(ROOT/'identifier-scope-amendment.json') if (ROOT/'identifier-scope-amendment.json').exists() else None
    if plan['pool_sha256']!=digest(DATA/'pool.json'):
        raise ValueError('Frozen source/train pool drift')
    cutoff,end=stamp(pool['cutoff']),stamp(pool['end'])
    state_path=DATA/'acquisition-state.json'
    state=read(state_path) if state_path.exists() else {'accepted':[],'rejected':[],'processed':[],'batches':0,'probe_complete':False}
    if args.probe and state['probe_complete']:
        print('Explicit-version probe already recorded',flush=True);return
    for path in (mf.ROOT/'rate-limit.json',CACHE/'rate-limit.json',__import__('pathlib').Path('.cache/stage12/rate-limit.json')):
        if path.exists() and stamp(read(path)['retry_not_before'])>datetime.now(timezone.utc):
            print('Official API cooldown active; no request sent',flush=True);return
    package=mf.upstream()
    mf.ROOT=CACHE
    delay=5.1 if (CACHE/'rate-limit.json').exists() else 3.1
    session=mf.RecordedSession('arxiv',delay)
    if args.direct:session.trust_env=False
    client=package.Client(page_size=50,delay_seconds=delay,num_retries=0);client._session=session
    processed=set(state['processed']);accepted_ids={r['doc_id'] for r in state['accepted']}
    counts=Counter(r['cohort'] for r in state['accepted'])
    batches=0
    CACHE.mkdir(parents=True,exist_ok=True)
    successful={};single_failures=set();single_failure_streak=0
    cached=[read(p) for p in sorted((CACHE/'batches').glob('*.json'))]
    for name in ('transport-format-probe.json','transport-legacy-single-probe.json'):
        if (CACHE/name).exists():cached.extend(read(CACHE/name))
    for receipt in cached:
        requested=receipt.get('requested_ids') or ([receipt['requested_id']] if 'requested_id' in receipt else [])
        statuses=[r['status'] for r in receipt.get('requests',[])]
        if len(requested)==1 and any(s in (500,502,503,504) for s in statuses):single_failures.add(requested[0])
        for row in receipt.get('records',[]):
            if 'categories' not in row:
                from pathlib import Path
                from gsearch.paper_identity import arxiv_identity
                raw=Path(row['provenance']['raw_path'])
                if digest(raw)!=row['provenance']['raw_sha256']:raise ValueError('Cached response hash changed')
                match=[r for r in package._feed.parse(raw.read_bytes()).results if arxiv_identity(r.entry_id)==(row['doc_id'],1)]
                if len(match)!=1:raise ValueError('Cached v1 result missing')
                row={**row,'categories':list(match[0].categories),'primary_category':match[0].primary_category}
            successful[row['doc_id']]=row
    for d in sorted(single_failures):
        if not any(r['doc_id']==d for r in state['rejected']):
            state['rejected'].append({'doc_id':d,'reason':'official singleton HTTP5xx; v1 not acquired, status unknown'})
    def native_fetch(ids: list[str]) -> dict[str,dict]:
        nonlocal batches,single_failure_streak
        if args.max_batches is not None and batches>=args.max_batches:
            raise StopIteration
        before=len(session.receipts);rows=[];error=None;started=time.perf_counter()
        try:
            for result in client.results(package.Search(id_list=[d+'v1' for d in ids],max_results=len(ids))):
                row=mf.record_api(result,session.receipts[-1])
                row['categories']=list(result.categories);row['primary_category']=result.primary_category
                if row['version']!=1 or row['doc_id'] not in ids or not row['title'].strip() or not row['abstract'].strip():
                    raise ValueError('Unexpected identity/version or missing original text')
                rows.append(row)
        except Exception as exc:
            error=type(exc).__name__+': '+str(exc)
        receipt={'requested_ids':ids,'records':rows,'error':error,'requests':session.receipts[before:],
                 'seconds':time.perf_counter()-started,'created_at':datetime.now(timezone.utc).isoformat()}
        out=CACHE/'batches'/f'{state["batches"]:05d}-{time.time_ns()}.json';save(out,receipt)
        state['batches']+=1;batches+=1
        if error:
            save(state_path,state)
            statuses=[r['status'] for r in receipt['requests']]
            if statuses and statuses[-1] in (500,502,503,504):
                if len(ids)==1:
                    single_failures.add(ids[0]);single_failure_streak+=1
                    state['rejected'].append({'doc_id':ids[0],'reason':'official singleton HTTP5xx; v1 not acquired, status unknown'})
                    if single_failure_streak>=5:raise RuntimeError('Five consecutive singleton HTTP5xx: stop source circuit')
                    return {}
                # Source-error isolation only; admission still follows the original pool order.
                modern=[d for d in ids if '/' not in d];legacy=[d for d in ids if '/' in d]
                parts=(modern,legacy) if modern and legacy else (ids[:len(ids)//2],ids[len(ids)//2:])
                combined={}
                for part in parts:combined.update(fetch(part))
                return combined
            raise RuntimeError(error)
        single_failure_streak=0
        by_id={r['doc_id']:r for r in rows}
        if len(by_id)!=len(rows):
            raise ValueError('Duplicate v1 source response')
        for d in ids:
            if d not in by_id:
                state['rejected'].append({'doc_id':d,'reason':'official v1 not returned, not proof of nonexistence'})
        successful.update(by_id)
        return by_id
    def fetch(ids: list[str]) -> dict[str,dict]:
        by_id={d:successful[d] for d in ids if d in successful}
        needed=[d for d in ids if d not in successful and d not in single_failures]
        if needed:by_id.update(native_fetch(needed))
        return by_id
    def accept(row: dict,cohort: str,day: str|None=None) -> bool:
        d=row['doc_id'];avail=available_at(row['published_at'])
        if d in accepted_ids or not set(row['categories'])&DOMAINS:
            return False
        if cohort!='new_cold' and not avail<cutoff:
            return False
        if cohort=='new_cold' and (not cutoff<=avail<=end or stamp(row['published_at']).date().isoformat()!=day):
            return False
        row={**row,'cohort':cohort,'available_at':avail.isoformat(),'version_key':'arxiv:'+d+'v1',
             'text_sha256':__import__('hashlib').sha256((row['title']+'\n'+row['abstract']).encode()).hexdigest(),
             'time_assumption':'submission-day end plus24h proxy; not historical first-ingest proof'}
        state['accepted'].append(row);accepted_ids.add(d);counts[cohort]+=1
        return True
    def checkpoint() -> None:
        state['processed']=sorted(processed);save(state_path,state)
        print(__import__('json').dumps({'accepted':dict(counts),'batches_this_run':batches,'total_batches':state['batches']}),flush=True)
    with FileLock(str(CACHE/'acquisition.lock')):
        try:
            if args.probe:
                probe=pool['warm'][:4]+pool['old_cold'][:4]+next(iter(pool['new_days'].values()))[:4]
                rows=fetch(probe)
                if len(rows)!=len(probe):
                    raise ValueError('Explicit-version preliminary probe incomplete')
                save(ROOT/'version-probe.json',{'requested':len(probe),'returned':len(rows),
                    'all_version1':all(r['version']==1 for r in rows.values()),'first_dates_present':all(stamp(r['published_at']) is not None for r in rows.values()),
                    'native_original_arxiv_parser':True,'domain_matches':sum(bool(set(r['categories'])&DOMAINS) for r in rows.values()),
                    'note':'Small source-only probe; does not select or score future labels'})
                state['probe_complete']=True;checkpoint();return
            if not state['probe_complete']:
                raise ValueError('Explicit-version probe required before bulk')
            for cohort in ('warm','old_cold'):
                source=[d for d in pool[cohort] if d not in processed and (scope is None or '/' not in d)]
                for start in range(0,len(source),50):
                    if counts[cohort]>=QUOTAS[cohort]:break
                    ids=source[start:start+50];rows=fetch(ids)
                    for d in ids:
                        processed.add(d)
                        if d in rows and counts[cohort]<QUOTAS[cohort]:
                            accept(rows[d],cohort)
                    checkpoint()
                if counts[cohort]<QUOTAS[cohort]:
                    raise ValueError('Predeclared pool exhausted for '+cohort)
            daily=Counter(stamp(r['published_at']).date().isoformat() for r in state['accepted'] if r['cohort']=='new_cold')
            for day,source in pool['new_days'].items():
                if counts['new_cold']>=QUOTAS['new_cold']:break
                remaining=[d for d in source if d not in processed and (scope is None or '/' not in d)]
                for start in range(0,len(remaining),50):
                    if daily[day]>=9 or counts['new_cold']>=QUOTAS['new_cold']:break
                    ids=remaining[start:start+50];rows=fetch(ids)
                    for d in ids:
                        processed.add(d)
                        if d in rows and daily[day]<9 and counts['new_cold']<QUOTAS['new_cold'] and accept(rows[d],'new_cold',day):
                            daily[day]+=1
                    checkpoint()
            checkpoint()
            if counts!=Counter(QUOTAS):
                raise ValueError('Incoming source-only daily quota did not fill1000; preserve incomplete result')
        except StopIteration:
            checkpoint()
        except Exception:
            checkpoint();raise

if __name__=='__main__':
    main()
