"""Train/source-only candidate admission with explicit arXiv v1 metadata."""
from collections import defaultdict
from datetime import datetime,timedelta,timezone
import hashlib
import heapq
import json
from pathlib import Path

import pandas as pd

from .catalog_audit import arrow,digest,read,stamp

ROOT=Path('reports/stage13')
DATA=Path('data/stage13-expansion')
CACHE=Path('.cache/stage13')
ORIGINAL=Path('data/stage9-recommendation')
DOMAINS={'cs.AI','cs.CL','cs.CV','cs.IR','cs.LG','cs.NE','cs.RO','stat.ML'}
QUOTAS={'warm':8000,'old_cold':1000,'new_cold':1000}
TIERS={1000:(800,100,100,1),5000:(4000,500,500,5),10000:(8000,1000,1000,9)}
SEED='stage13-fixed-v1-admission-20261026'

def save(path: Path,obj: object) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=lambda x:x.isoformat()),encoding='utf-8')

def key(doc: str) -> str:
    return hashlib.sha256((SEED+':'+doc).encode()).hexdigest()

def available_at(published: object) -> datetime:
    t=stamp(published)
    if t is None:
        raise ValueError('Missing version publication/submission time')
    # End of submission day plus24h: explicit conservative proxy, not an announcement log.
    return t.replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=2)

def bootstrap() -> None:
    if (DATA/'pool.json').exists():
        raise ValueError('Refuse to overwrite candidate acquisition pool')
    audit=read(ORIGINAL/'audit.json')
    cutoff=stamp(audit['cutoffs']['train_exclusive'])
    end=stamp('2025-02-23T05:28:26.401006+00:00')
    train=pd.read_csv(ORIGINAL/'train.csv',dtype={'arxiv_id':str,'user_id':str})
    counts=train.loc[train.rating==1,'arxiv_id'].value_counts().to_dict()
    warm=sorted(counts,key=lambda d:(-counts[d],d))
    liked=set(warm)
    old=[]
    days=defaultdict(list)
    arrow()
    import pyarrow.parquet as pq
    source_manifest=read(Path('reports/stage12/coverage-aggregate.json'))['source_parts_sha256']
    for path in sorted(Path('.cache/stage12/light').glob('group-*.parquet')):
        if digest(path)!=source_manifest[path.name]:
            raise ValueError('Frozen source date part changed')
        for row in pq.read_table(path,columns=['paper_id','first_version_date']).to_pylist():
            d=row['paper_id']
            if d in liked:
                continue
            try:
                avail=available_at(row['first_version_date'])
            except ValueError:
                continue
            entry=(key(d),d)
            if avail<cutoff:
                old.append(entry)
                if len(old)>=40000:
                    old=heapq.nsmallest(20000,old)
            elif avail<=end:
                day=stamp(row['first_version_date']).date().isoformat()
                days[day].append(entry)
                if len(days[day])>300:
                    days[day]=heapq.nsmallest(150,days[day])
    old_ids=[d for _,d in heapq.nsmallest(20000,old)]
    new_days={day:[d for _,d in sorted(items)[:150]] for day,items in sorted(days.items())}
    pool={'warm':warm,'old_cold':old_ids,'new_days':new_days,
          'cutoff':cutoff.isoformat(),'end':end.isoformat(),'future_labels_used':False,
          'feedback_sha256':digest(ORIGINAL/'train.csv'),'source_manifest_sha256':digest(Path('reports/stage12/coverage-aggregate.json'))}
    save(DATA/'pool.json',pool)
    plan={'quotas':QUOTAS,'tiers':{str(k):list(v) for k,v in TIERS.items()},'domains':sorted(DOMAINS),
        'seed':SEED,'version':1,'pool_sha256':digest(DATA/'pool.json'),'cutoff':pool['cutoff'],'end':pool['end'],
        'admission':'Warm train frequency/ID; old no-train-like fixed hash; incoming per source submission day fixed hash, verify v1 date/category, admit at most9 daily, cap1000. New date mismatch rejected, not moved backwards.',
        'time_assumption':'Version1 submitted/processed date at end of day plus24h; not verified historical announcement/first-ingest. Source-frame completeness is a retrospective snapshot assumption.',
        'domain':'Exact category membership in official v1 record only; no latest-version category prefilter',
        'resource_limits':{'peak_working_set_gib':6,'peak_private_commit_gib':8,'fit_timeout_seconds':180},
        'evaluation':'All original future positive events, frozen train history. Predict immediately before recorded positive event using the shared as-of directory. Per-event singleton Recall/NDCG, macro average within user then users. Conditional positive-event retrospective ranking, not real exposure/CTR. Re-evaluate1000/5000/10000 with same protocol; old stage11 NDCG not directly comparable.',
        'tuning':'Select each tier alpha in0,.25,.5,.75,1 by user-macro NDCG then Recall/MRR, ties endpoint then smaller alpha; freeze all before dev. Endpoint uses exact single branch.',
        'cost':'Quality can reuse time-invariant component scores per user; inference latency measured separately without that cache on a deterministic256-event sample, rotated method order.',
        'history':'all train positive/negative seen mask identical; SAR/content profiles use same eligible train-positive item vocabulary; new or zero-content-profile fallback explicit',
        'heldout':'All future likes including out-of-catalog/not-yet-available counted as misses. Existing dev descriptive, no fresh independent source period.',
        'code_sha256':digest(Path(__file__))}
    save(ROOT/'admission-plan.json',plan)
    print(json.dumps({'warm_pool':len(warm),'old_cold_pool':len(old_ids),'incoming_days':len(new_days),'incoming_pool':sum(map(len,new_days.values()))}),flush=True)

def tier_records(records: list[dict],n: int) -> list[dict]:
    warm,old,new,daily=TIERS[n]
    initial=[r for r in records if r['cohort']=='warm'][:warm]+[r for r in records if r['cohort']=='old_cold'][:old]
    per_day=defaultdict(int)
    added=[]
    for r in records:
        if r['cohort']!='new_cold':
            continue
        day=stamp(r['published_at']).date().isoformat()
        if per_day[day]<daily and len(added)<new:
            added.append(r)
            per_day[day]+=1
    if len(initial)+len(added)!=n:
        raise ValueError(f'Tier{n} does not meet its predeclared quotas')
    return initial+added

def finalize() -> None:
    if (DATA/'documents.json').exists():
        raise ValueError('Refuse to replace frozen version corpus')
    state=read(DATA/'acquisition-state.json')
    records=state['accepted']
    counts={c:sum(r['cohort']==c for r in records) for c in QUOTAS}
    if counts!=QUOTAS or len({r['doc_id'] for r in records})!=10000:
        raise ValueError('Incomplete or duplicate version corpus')
    for r in records:
        if r['version']!=1 or not r['title'].strip() or not r['abstract'].strip() or not (set(r['categories'])&DOMAINS):
            raise ValueError('Version/text/domain contract failed')
        if stamp(r['available_at'])!=available_at(r['published_at']):
            raise ValueError('As-of timestamp contract failed')
    save(DATA/'documents.json',records)
    for n in TIERS:
        save(DATA/f'catalog-{n}.json',[r['doc_id'] for r in tier_records(records,n)])
    save(ROOT/'corpus-receipt.json',{'counts':counts,'documents_sha256':digest(DATA/'documents.json'),
        'catalogs':{str(n):digest(DATA/f'catalog-{n}.json') for n in TIERS},'acquisition_state_sha256':digest(DATA/'acquisition-state.json'),
        'admission_plan_sha256':digest(ROOT/'admission-plan.json'),'version':1,'fields':'Original official arXiv v1 metadata, no synthesized titles/abstracts'})
    print(json.dumps({'frozen_corpus':counts}),flush=True)

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--phase',choices=('bootstrap','finalize'),required=True)
    a=p.parse_args();(bootstrap if a.phase=='bootstrap' else finalize)()
