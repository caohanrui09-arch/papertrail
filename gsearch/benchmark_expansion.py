"""Positive-event retrospective replay with frozen histories and shared as-of candidates."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd

from .expansion_data import DATA,ROOT,ORIGINAL,TIERS,save,read
from .catalog_audit import digest,stamp
from .content_recommendation import sklearn_runtime,ALPHAS
from .expansion_recommendation import load,signature

SINGLES=('popular','sar','content')
FUSIONS={f'hybrid_a{round(a*100):03d}':a for a in ALPHAS}

def state() -> dict:
    files=('gsearch/expansion_data.py','gsearch/expansion_recommendation.py','gsearch/benchmark_expansion.py','gsearch/paper_recommendation.py')
    return {'code':{p:digest(Path(p)) for p in files},'runtime':sklearn_runtime(),
        'corpus_receipt_sha256':digest(ROOT/'corpus-receipt.json'),'documents_sha256':digest(DATA/'documents.json'),
        'feedback':{s:digest(ORIGINAL/(s+'.csv')) for s in ('train','tuning','dev')},
        'admission_plan_sha256':digest(ROOT/'admission-plan.json'),
        'identifier_scope_amendment_sha256':digest(ROOT/'identifier-scope-amendment.json'),
        'resource_gates_sha256':digest(ROOT/'resource-gates.json')}

def check_plan() -> dict:
    p=read(ROOT/'evaluation-plan.json')
    if p['state']!=state():raise ValueError('Expansion evaluation protocol drift')
    return p

def pick(result: dict) -> tuple:
    s=result['summary'];return s['ndcg@10'],s['recall@10'],s['mrr@10']

def events(split: str) -> pd.DataFrame:
    f=pd.read_csv(ORIGINAL/(split+'.csv'),dtype={'user_id':str,'arxiv_id':str})
    f=f[f.rating==1].copy()
    f['at']=pd.to_datetime(f.time,format='mixed',utc=True)
    return f.sort_values(['user_id','at','arxiv_id'],kind='stable').reset_index(drop=True)

def evaluate(split: str,tier: int) -> None:
    check_plan();sklearn_runtime()
    from threadpoolctl import threadpool_limits
    if split=='tuning':
        methods={m:(m,None) for m in SINGLES}|{m:('hybrid',a) for m,a in FUSIONS.items()}
    else:
        lock=read(ROOT/'locked-before-dev.json')
        methods={m:(m,None) for m in SINGLES}|{'hybrid':('hybrid',lock['tiers'][str(tier)]['alpha'])}
    if any((ROOT/f'{tier}-{m}-{split}.json').exists() for m in methods):raise ValueError('Refuse to overwrite evaluation')
    with threadpool_limits(limits=1):
        model=load(tier)
        expected=read(ROOT/f'resource-{tier}.json')['model_signature']
        if signature(model)!=expected:raise ValueError('Resource/tuning/dev train-only fit differs')
        f=events(split);n=len(f)
        indices={m:np.full((n,10),-1,dtype=np.int32) for m in methods}
        available_gold=np.zeros(n,dtype=bool);cold_user=np.zeros(n,dtype=bool)
        known_train=pd.read_csv(ORIGINAL/'train.csv',dtype={'arxiv_id':str,'user_id':str},usecols=['arxiv_id','user_id','rating'])
        global_likes=set(known_train.loc[known_train.rating==1,'arxiv_id'])
        cold_item=~f.arxiv_id.isin(global_likes).to_numpy()
        started=time.perf_counter()
        user_groups=list(f.groupby('user_id',sort=True))
        component_cache={}
        for number,(user,group) in enumerate(user_groups):
            if number%64==0:
                names=[u for u,_ in user_groups[number:number+64]]
                cf,text=model.batch_components(names)
                component_cache={u:(cf[j],text[j]) for j,u in enumerate(names)}
            components=component_cache[user]
            last_day=None;daily={}
            for row in group.itertuples():
                day=row.at.date()
                if day!=last_day:
                    eligible=model.eligible(user,row.at.to_pydatetime())
                    daily={name:model.rank_indices(user,row.at.to_pydatetime(),mode,10,.5 if a is None else a,
                        components=components,eligible_indices=eligible) for name,(mode,a) in methods.items()}
                    last_day=day
                target=model.position.get(row.arxiv_id,-1)
                available_gold[row.Index]=target>=0 and target in eligible
                cold_user[row.Index]=user not in model.user2row
                for name in methods:
                    hits=daily[name];indices[name][row.Index,:len(hits)]=hits
                    if any(model.catalog[int(i)] in model.sar.seen.get(user,set()) for i in hits):
                        raise ValueError('Known train rating entered output')
            if (number+1)%1000==0:print(json.dumps({'tier':tier,'split':split,'users_done':number+1}),flush=True)
        quality_seconds=time.perf_counter()-started
        target_idx=np.array([model.position.get(d,-2) for d in f.arxiv_id],dtype=np.int32)
        raw_event_path=DATA/f'{tier}-{split}-events.json'
        event_rows=[{'user_id':r.user_id,'arxiv_id':r.arxiv_id,'time':r.time,'available_gold':bool(available_gold[r.Index]),
                    'cold_user':bool(cold_user[r.Index]),'cold_item_global':bool(cold_item[r.Index])} for r in f.itertuples()]
        save(raw_event_path,event_rows)
        users={u:g.index.to_numpy() for u,g in f.groupby('user_id',sort=True)}
        for name in methods:
            predictions=indices[name]
            equal=predictions==target_idx[:,None]
            rank=np.where(equal.any(axis=1),equal.argmax(axis=1)+1,0)
            recall=(rank>0).astype(float)
            ndcg=np.divide(1,np.log2(rank+1),out=np.zeros(n),where=rank>0)
            mrr=np.divide(1,rank,out=np.zeros(n),where=rank>0)
            rows=[]
            for u,ix in users.items():
                rows.append({'user_id':u,'relevant':sorted(f.loc[ix,'arxiv_id'].tolist()),'events':len(ix),
                    'recall':float(recall[ix].mean()),'ndcg':float(ndcg[ix].mean()),'mrr':float(mrr[ix].mean()),
                    'cold_user':bool(cold_user[ix[0]]),'available_gold_fraction':float(available_gold[ix].mean())})
            summary={k+'@10':sum(r[k] for r in rows)/len(rows) for k in ('recall','ndcg','mrr')}
            summary.update({'users':len(rows),'positive_events':n,'warm_users':sum(not r['cold_user'] for r in rows),
                'cold_users':sum(r['cold_user'] for r in rows),'candidate_budget':tier,
                'catalog_coverage':len(set(predictions[predictions>=0].tolist()))/tier,
                'eligible_gold_event_fraction':float(available_gold.mean()),
                'eligible_gold_user_macro_fraction':sum(r['available_gold_fraction'] for r in rows)/len(rows)})
            groups={}
            for warm in (True,False):
                records=[r for r in rows if (not r['cold_user'])==warm]
                groups['warm_user' if warm else 'cold_user']={'users':len(records),**{
                    k:sum(r[k] for r in records)/len(records) if records else None for k in ('recall','ndcg','mrr')}}
            cross={}
            for uc in (False,True):
                for ic in (False,True):
                    mask=(cold_user==uc)&(cold_item==ic)
                    cross[f'{"cold" if uc else "warm"}_user__{"cold" if ic else "warm"}_item']={
                        'events':int(mask.sum()),'recall':float(recall[mask].mean()) if mask.any() else None,
                        'ndcg':float(ndcg[mask].mean()) if mask.any() else None}
            raw=DATA/f'{tier}-{name}-{split}.npz'
            np.savez_compressed(raw,indices=predictions)
            userpath=DATA/f'{tier}-{name}-{split}-users.json';save(userpath,rows)
            result={'tier':tier,'method':name,'split':split,'summary':summary,'user_groups':groups,'event_cold_cross':cross,
               'raw_predictions_sha256':digest(raw),'events_sha256':digest(raw_event_path),'users_sha256':digest(userpath),
               'catalog_order_sha256':expected['catalog_sha256'],'model_signature':expected,
               'evaluation_plan_sha256':digest(ROOT/'evaluation-plan.json'),'fit':model.fit,
               'quality_replay_seconds_all_methods':quality_seconds,
               'metric_note':'singleton gold per recorded positive event; macro average within each user then users; NDCG differs from old period-list metric',
               'cost_note':'Quality batches original scorers64 users, reuses time-invariant component scores/user and rankings/day; this is not per-request service latency'}
            save(ROOT/f'{tier}-{name}-{split}.json',result)
            print(json.dumps({'tier':tier,'method':name,'split':split,'summary':summary}),flush=True)
        if split=='dev':
            alpha=methods['hybrid'][1]
            order=sorted(range(n),key=lambda i:hashlib.sha256(('stage13-latency:'+f.at[i,'user_id']+':'+f.at[i,'time']).encode()).hexdigest())[:256]
            latency={m:[] for m in methods}
            for position,i in enumerate(order):
                row=f.iloc[i];names=list(methods);rotate=position%len(names);names=names[rotate:]+names[:rotate]
                for m in names:
                    mode,a=methods[m]
                    t=time.perf_counter();model.recommend(row.user_id,row['at'].to_pydatetime(),mode,10,.5 if a is None else a)
                    latency[m].append(time.perf_counter()-t)
            save(ROOT/f'{tier}-latency-dev.json',{'tier':tier,'requests':len(order),'cold_users_in_sample':int(cold_user[order].sum()),
                'single_numerical_thread':True,'component_score_cache':False,'rotated_method_order':True,
                'methods':{m:{'mean_ms':float(np.mean(v)*1000),'median_ms':float(np.median(v)*1000),'p95_ms':float(np.quantile(v,.95)*1000)} for m,v in latency.items()}})

def main() -> None:
    p=argparse.ArgumentParser();p.add_argument('--phase',choices=('plan','tuning','lock','dev'),required=True)
    p.add_argument('--tier',type=int,choices=tuple(TIERS));a=p.parse_args()
    if a.phase=='plan':
        if (ROOT/'evaluation-plan.json').exists():raise ValueError('Evaluation plan exists')
        if not all(r['passed'] for r in read(ROOT/'resource-gates.json')):raise ValueError('Resource gate failure')
        save(ROOT/'evaluation-plan.json',{'state':state(),'alphas':list(ALPHAS),'tiers':list(TIERS),
          'metric':'user-macro of per-positive-event singleton Recall/NDCG/MRR; immediate-before-event request with frozen training history',
          'causality':'as-of mask before ranking/RRF, future documents transform only, no future-label training or admission',
          'latency':'separate uncached256 deterministic observed-event requests, rotated order; quality replay timings not request latency',
          'selection':'each tier NDCG then Recall/MRR; fusion ties endpoints then lower alpha; single ties popular/SAR/content',
          'dev':'descriptive reused; all future positives retained, no independent-source claim'})
        return
    check_plan()
    if a.phase=='lock':
        if (ROOT/'locked-before-dev.json').exists():raise ValueError('Selection already frozen')
        tiers={};hashes={}
        for n in TIERS:
            results={m:read(ROOT/f'{n}-{m}-tuning.json') for m in (*SINGLES,*FUSIONS)}
            chosen=max(FUSIONS,key=lambda m:(*pick(results[m]),FUSIONS[m] in (0,1),-FUSIONS[m]))
            single=max(SINGLES,key=lambda m:(*pick(results[m]),-SINGLES.index(m)))
            tiers[str(n)]={'alpha':FUSIONS[chosen],'selected':chosen,'best_single':single}
            hashes.update({f'{n}-{m}-tuning.json':digest(ROOT/f'{n}-{m}-tuning.json') for m in results})
        save(ROOT/'locked-before-dev.json',{'tiers':tiers,'tuning_results_sha256':hashes,'plan_sha256':digest(ROOT/'evaluation-plan.json')})
        print(json.dumps(tiers),flush=True);return
    if a.tier is None:raise ValueError('Tier required')
    if a.phase=='dev':
        lock=read(ROOT/'locked-before-dev.json')
        if lock['plan_sha256']!=digest(ROOT/'evaluation-plan.json') or any(digest(ROOT/n)!=v for n,v in lock['tuning_results_sha256'].items()):raise ValueError('Selection drift')
    evaluate(a.phase,a.tier)

if __name__=='__main__':main()
