"""Train-only baselines on the same 9000 candidates and last20 positive context."""
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd
import psutil
from scipy import sparse
from sklearn.preprocessing import normalize
from threadpoolctl import threadpool_limits

from gsearch.paper_recommendation import upstream_sar
from gsearch.quality_protocol import digest,save
from gsearch.supervision import json_rows

DATA=Path('data/stage45-sft');REPORT=Path('reports/stage45')


def main() -> None:
    design=json.loads((REPORT/'baseline-design.json').read_text())
    for path,expected in design['files'].items():
        assert digest(Path(path))==expected
    if (REPORT/'baseline-cost.json').exists():raise FileExistsError('Preserve baselines')
    start=time.perf_counter()
    ids=json.loads((DATA/'text-vocabulary.json').read_text())['ids'];position={d:i for i,d in enumerate(ids)}
    vectors=sparse.load_npz(DATA/'content-tfidf.npz')
    profiles={r['user_key']:r for r in json_rows(Path('data/stage44-supervision/profiles.jsonl'))}
    inputs=list(json_rows(Path('data/stage44-supervision/tuning.inputs.jsonl')))
    users=sorted({r['user_key'] for r in inputs})
    counts=json.loads(Path('data/stage44-supervision/popularity.json').read_text())['counts']
    popular=np.array([counts.get(d,0) for d in ids],dtype=float)
    feedback=pd.DataFrame(json_rows(Path('data/stage44-supervision/train.feedback.jsonl')))
    positive=feedback[(feedback.rating==1)&feedback.available_at_event].copy()
    native=upstream_sar()(col_user='user_key',col_item='doc_id',col_rating='rating',
        similarity_type='jaccard',threshold=1,timedecay_formula=False,normalize=False)
    positive['rating']=positive.rating.astype(float)
    with threadpool_limits(limits=2):
        fit=time.perf_counter();native.fit(positive[['user_key','doc_id','rating']]);fit_seconds=time.perf_counter()-fit
        warm_positions=np.array([position[native.index2item[i]] for i in range(native.n_items)])
        predictions={method:{} for method in ['popular','content','sar']};times=[];verified=0
        for start_index in range(0,len(users),64):
            batch=users[start_index:start_index+64];clock=time.perf_counter()
            rows=[];cols=[];sar_rows=[];sar_cols=[]
            for i,user in enumerate(batch):
                for doc in profiles.get(user,{}).get('history_doc_ids',[]):
                    rows.append(i);cols.append(position[doc])
                    if doc in native.item2index:
                        sar_rows.append(i);sar_cols.append(native.item2index[doc])
            context=sparse.csr_matrix((np.ones(len(rows)),(rows,cols)),shape=(len(batch),len(ids)))
            interest=normalize(context@vectors)
            content=(interest@vectors.T).toarray()
            affinity=sparse.csr_matrix((np.ones(len(sar_rows)),(sar_rows,sar_cols)),shape=(len(batch),native.n_items))
            native_scores=affinity@native.item_similarity
            for i,user in enumerate(batch):
                history=profiles.get(user,{}).get('history_doc_ids',[])
                seen=set(profiles.get(user,{}).get('seen_doc_ids',[]))
                eligible=np.array([j for j,d in enumerate(ids) if d not in seen])
                fallback=not profiles.get(user,{}).get('eligible_train_positive_count',0)
                sar=np.zeros(len(ids));sar[warm_positions]=native_scores[i]
                for method,values in [('popular',popular),('content',content[i]),('sar',sar)]:
                    scores=popular if fallback else values
                    ranked=eligible[np.argsort(-scores[eligible],kind='stable')[:10]]
                    predictions[method][user]=[ids[j] for j in ranked]
                if history and verified<3:
                    seed_docs=[d for d in history if d in native.item2index]
                    official=native.get_item_based_topk(pd.DataFrame({'doc_id':seed_docs}),top_k=native.n_items)
                    for row in official.to_dict('records'):
                        assert np.isclose(row['prediction'],sar[position[row['doc_id']]],atol=1e-12)
                    verified+=1
            times.append({'users':len(batch),'seconds':time.perf_counter()-clock})
    for method,by_user in predictions.items():
        with (DATA/(method+'.tuning.predictions.jsonl')).open('x',encoding='utf-8',newline='\n') as handle:
            for row in inputs:
                handle.write(json.dumps({'qid':row['qid'],'doc_ids':by_user[row['user_key']]},separators=(',',':'))+'\n')
    save(REPORT/'baseline-cost.json',{'fit_sar_seconds':fit_seconds,'total_seconds':time.perf_counter()-start,
        'sar_items':native.n_items,'native_pseudo_history_score_checks':verified,'batch_costs_combined':times,
        'peak_process_bytes':psutil.Process().memory_info().peak_wset,
        'scope':'same last20 context; native SAR fitted on all eligible train positives; dense zero for no-interaction candidates; fixed training ties',
        'files':{str(DATA/(m+'.tuning.predictions.jsonl')):digest(DATA/(m+'.tuning.predictions.jsonl')) for m in predictions}})
    print({'baselines':'completed','users':len(users),'events':len(inputs),'seconds':time.perf_counter()-start},flush=True)


if __name__=='__main__':main()
