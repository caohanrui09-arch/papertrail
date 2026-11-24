"""Source-only admission proof and independent NumPy/Pandas replay rescoring."""
from collections import Counter,defaultdict
from pathlib import Path
import hashlib

import numpy as np
import pandas as pd

from gsearch.expansion_data import DATA,CACHE,ROOT,ORIGINAL,DOMAINS,QUOTAS,TIERS,available_at,tier_records,read
from gsearch.catalog_audit import digest,stamp
from gsearch.paper_identity import arxiv_identity
from gsearch.benchmark_expansion import SINGLES,FUSIONS,events

def validate_corpus() -> dict:
    from gsearch.metadata_fetch import upstream
    native=upstream()
    records=read(DATA/'documents.json');receipt=read(ROOT/'corpus-receipt.json')
    plan=read(ROOT/'admission-plan.json');pool=read(DATA/'pool.json')
    state=read(DATA/'acquisition-state.json')
    if (digest(DATA/'documents.json')!=receipt['documents_sha256'] or digest(DATA/'pool.json')!=plan['pool_sha256'] or
            digest(ORIGINAL/'train.csv')!=pool['feedback_sha256'] or plan['code_sha256']!=digest(Path('gsearch/expansion_data.py'))):
        raise ValueError('Frozen source/train admission contract changed')
    if Counter(r['cohort'] for r in records)!=Counter(QUOTAS) or len({r['doc_id'] for r in records})!=10000:
        raise ValueError('Corpus quota/identity mismatch')
    cutoff,end=stamp(plan['cutoff']),stamp(plan['end'])
    train=pd.read_csv(ORIGINAL/'train.csv',dtype={'arxiv_id':str,'user_id':str})
    liked=set(train.loc[train.rating==1,'arxiv_id'])
    grouped=defaultdict(list)
    for r in records:grouped[r['provenance']['raw_path']].append(r)
    version_dates_equal=0
    for path,rows in grouped.items():
        raw=Path(path);h=digest(raw)
        parsed=native._feed.parse(raw.read_bytes())
        by_id={arxiv_identity(r.entry_id):r for r in parsed.results}
        for row in rows:
            d=row['doc_id'];original=by_id.get((d,1))
            if (row['provenance']['raw_sha256']!=h or original is None or '/' in d or row['version']!=1 or
                 row['version_key']!='arxiv:'+d+'v1' or row['title']!=original.title or row['abstract']!=original.summary or
                 row['categories']!=list(original.categories) or not set(row['categories'])&DOMAINS or
                 row['source_url']!='https://arxiv.org/abs/'+d+'v1' or
                 stamp(row['published_at'])!=original.published or stamp(row['available_at'])!=available_at(original.published) or
                 hashlib.sha256((row['title']+'\n'+row['abstract']).encode()).hexdigest()!=row['text_sha256']):
                raise ValueError('Original native-parsed v1/domain/time binding mismatch')
            version_dates_equal+=original.published==original.updated
            if row['cohort']=='warm':
                if d not in liked or not stamp(row['available_at'])<cutoff:raise ValueError('Invalid warm training item')
            elif d in liked:raise ValueError('Cold paper has train positive')
            if row['cohort']=='old_cold' and not stamp(row['available_at'])<cutoff:raise ValueError('Invalid initial cold text time')
            if row['cohort']=='new_cold' and not cutoff<=stamp(row['available_at'])<=end:raise ValueError('Invalid incoming proxy time')
    # Reconstruct admissions from successful source responses, never future labels.
    successful={}
    for path in sorted((CACHE/'batches').glob('*.json')):
        for r in read(path)['records']:
            if r.get('version')==1 and 'categories' in r:successful[r['doc_id']]=r
    for name in ('transport-format-probe.json','transport-legacy-single-probe.json'):
        if (CACHE/name).exists():
            for response in read(CACHE/name):
                for r in response.get('records',[]):
                    if 'categories' in r:successful.setdefault(r['doc_id'],r)
    processed=set(state['processed'])
    def eligible(d: str,cohort: str,day: str|None=None) -> bool:
        r=successful.get(d)
        if r is None:return False
        avail=available_at(r['published_at'])
        if not set(r['categories'])&DOMAINS:return False
        if cohort=='new_cold':return cutoff<=avail<=end and stamp(r['published_at']).date().isoformat()==day
        return avail<cutoff
    reconstructed={}
    for cohort in ('warm','old_cold'):
        selected=[]
        for d in pool[cohort]:
            if '/' in d:continue
            if d not in processed:raise ValueError('Unresolved acquisition predecessor before quota boundary')
            if eligible(d,cohort):selected.append(d)
            if len(selected)==QUOTAS[cohort]:break
        reconstructed[cohort]=selected
    incoming=[];daily=Counter()
    for day,ids in pool['new_days'].items():
        for d in ids:
            if '/' in d:continue
            if daily[day]>=9 or len(incoming)>=1000:break
            if d not in processed:raise ValueError('Unresolved incoming predecessor')
            if eligible(d,'new_cold',day):incoming.append(d);daily[day]+=1
        if len(incoming)>=1000:break
    reconstructed['new_cold']=incoming
    for cohort in QUOTAS:
        if reconstructed[cohort]!=[r['doc_id'] for r in records if r['cohort']==cohort]:
            raise ValueError('Source/train-only admission did not reproduce')
    previous=set()
    for n in TIERS:
        selected=tier_records(records,n)
        ids={r['doc_id'] for r in selected}
        if len(ids)!=n or not previous<=ids or [r['doc_id'] for r in selected]!=read(DATA/f'catalog-{n}.json'):
            raise ValueError('Nested resource/evaluation catalogs mismatch')
        previous=ids
    statuses=Counter();bytes_returned=0;requests=0;native_seconds=0
    receipts=[read(p) for p in sorted((CACHE/'batches').glob('*.json'))]
    for name in ('transport-format-probe.json','transport-legacy-single-probe.json'):
        if (CACHE/name).exists():receipts.extend(read(CACHE/name))
    for r in receipts:
        native_seconds+=r.get('seconds',0)
        for req in r.get('requests',[]):
            if digest(Path(req['raw_path']))!=req['raw_sha256']:raise ValueError('Transport raw response changed')
            statuses[str(req['status'])]+=1;bytes_returned+=req['bytes'];requests+=1
    return {'verified_records':len(records),'unique_official_raw_bodies':len(grouped),'native_v1_published_equals_updated':version_dates_equal,
        'admission_reproduced':True,'tiers_nested':True,'incoming_days_with_admissions':len(daily),
        'source_requests':requests,'http_status_counts':dict(statuses),'response_body_bytes':bytes_returned,
        'recorded_native_request_seconds':native_seconds,'source_rejection_records':len(state['rejected']),
        'unique_source_failures_unknown':len({r['doc_id'] for r in state['rejected']}),
        'new_cohort_published_after_train_cutoff':sum(stamp(r['published_at'])>=cutoff for r in records if r['cohort']=='new_cold'),
        'source_scope':'modern IDs; source failures not claimed as nonexistence; all original future labels kept'}

def validate_outputs() -> tuple[dict,dict,dict]:
    records=read(DATA/'documents.json');train=pd.read_csv(ORIGINAL/'train.csv',dtype={'arxiv_id':str,'user_id':str})
    all_likes=set(train.loc[train.rating==1,'arxiv_id']);seen=train.groupby('user_id').arxiv_id.agg(set).to_dict()
    result_map={};user_map={};checked={}
    for n in TIERS:
        subset=tier_records(records,n);by_id={r['doc_id']:r for r in subset};catalog=sorted(by_id)
        position={d:i for i,d in enumerate(catalog)}
        warm={r['doc_id'] for r in subset if r['cohort']=='warm'}
        warm_users=set(train.loc[(train.rating==1)&train.arxiv_id.isin(warm),'user_id'])
        available=np.array([stamp(by_id[d]['available_at']).timestamp() for d in catalog])
        for split in ('tuning','dev'):
            f=events(split);saved_events=read(DATA/f'{n}-{split}-events.json')
            if [(r['user_id'],r['arxiv_id'],r['time']) for r in saved_events]!=list(f[['user_id','arxiv_id','time']].itertuples(index=False,name=None)):
                raise ValueError('Evaluation cohort/gold changed')
            target=np.array([position.get(d,-2) for d in f.arxiv_id],dtype=np.int32)
            at=np.array([t.timestamp() for t in f['at']])
            uc=~f.user_id.isin(warm_users).to_numpy();ic=~f.arxiv_id.isin(all_likes).to_numpy()
            gold_available=np.array([i>=0 and available[i]<=t and d not in seen.get(u,set()) for i,t,d,u in zip(target,at,f.arxiv_id,f.user_id)])
            if ([r['cold_user'] for r in saved_events]!=uc.tolist() or [r['cold_item_global'] for r in saved_events]!=ic.tolist() or
                 [r['available_gold'] for r in saved_events]!=gold_available.tolist()):raise ValueError('As-of/cold event flags differ')
            groups={u:g.index.to_numpy() for u,g in f.groupby('user_id',sort=True)}
            methods=(*SINGLES,*FUSIONS) if split=='tuning' else (*SINGLES,'hybrid')
            arrays={}
            for method in methods:
                result=read(ROOT/f'{n}-{method}-{split}.json');raw=DATA/f'{n}-{method}-{split}.npz'
                user_path=DATA/f'{n}-{method}-{split}-users.json'
                if (digest(raw)!=result['raw_predictions_sha256'] or digest(user_path)!=result['users_sha256'] or
                    digest(DATA/f'{n}-{split}-events.json')!=result['events_sha256'] or digest(ROOT/'evaluation-plan.json')!=result['evaluation_plan_sha256']):
                    raise ValueError('Frozen prediction hash mismatch')
                with np.load(raw,allow_pickle=False) as data:pred=data['indices']
                if pred.shape!=(len(f),10) or (pred>=n).any() or (pred<-1).any():raise ValueError('Invalid raw ranked index array')
                valid=pred>=0
                if (valid & (available[np.maximum(pred,0)]>at[:,None])).any():raise ValueError('Future paper in output')
                ordered=np.sort(pred,axis=1)
                if ((ordered[:,1:]==ordered[:,:-1])&(ordered[:,1:]>=0)).any():raise ValueError('Duplicate recommendation')
                equal=pred==target[:,None];rank=np.where(equal.any(axis=1),equal.argmax(axis=1)+1,0)
                scores={'recall':(rank>0).astype(float),
                    'ndcg':np.divide(1,np.log2(rank+1),out=np.zeros(len(f)),where=rank>0),
                    'mrr':np.divide(1,rank,out=np.zeros(len(f)),where=rank>0)}
                user_rows=read(user_path)
                if [r['user_id'] for r in user_rows]!=list(groups):raise ValueError('Missing evaluation users')
                for row,(u,ix) in zip(user_rows,groups.items()):
                    known=[position[d] for d in seen.get(u,set()) if d in position]
                    if np.isin(pred[ix],known).any():raise ValueError('Known train rating recommended')
                    if row['relevant']!=sorted(f.loc[ix,'arxiv_id'].tolist()) or row['events']!=len(ix):raise ValueError('Future positives omitted')
                    for metric,a in scores.items():
                        if abs(row[metric]-a[ix].mean())>1e-12:raise ValueError('Raw metric recount differs')
                for metric in scores:
                    if abs(np.mean([r[metric] for r in user_rows])-result['summary'][metric+'@10'])>1e-12:raise ValueError('Macro aggregation differs')
                if abs(gold_available.mean()-result['summary']['eligible_gold_event_fraction'])>1e-12:raise ValueError('Catalog reachability differs')
                if abs(len(set(pred[valid].tolist()))/n-result['summary']['catalog_coverage'])>1e-12:raise ValueError('Coverage differs')
                for cold in (False,True):
                    rows=[r for r in user_rows if r['cold_user']==cold]
                    group=result['user_groups']['cold_user' if cold else 'warm_user']
                    if group['users']!=len(rows):raise ValueError('User group count differs')
                    for metric in scores:
                        if abs(np.mean([r[metric] for r in rows])-group[metric])>1e-12:raise ValueError('User group score differs')
                    for cold_paper in (False,True):
                        mask=(uc==cold)&(ic==cold_paper)
                        r=result['event_cold_cross'][f'{"cold" if cold else "warm"}_user__{"cold" if cold_paper else "warm"}_item']
                        if r['events']!=int(mask.sum()):raise ValueError('Cold cross count differs')
                        for metric in ('recall','ndcg'):
                            if mask.any() and abs(r[metric]-scores[metric][mask].mean())>1e-12:raise ValueError('Cold cross metric differs')
                arrays[method]=pred;result_map[n,split,method]=result;user_map[n,split,method]=user_rows
                checked[f'{n}-{method}-{split}']=len(f)
            for method,pred in arrays.items():
                if not np.array_equal(pred[uc],arrays['popular'][uc]):raise ValueError('Cold fallback differs')
            if split=='tuning':
                for endpoint,single in (('hybrid_a000','content'),('hybrid_a100','sar')):
                    if not np.array_equal(arrays[endpoint],arrays[single]):raise ValueError('Fusion endpoint differs')
    return result_map,user_map,checked
