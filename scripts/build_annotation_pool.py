"""Prepare an unjudged pool for nine revised tuning requests with native scorers."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import time

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from gsearch.visitor_profile import Catalog
from gsearch.expansion_recommendation import ExpansionRecommender
from gsearch.quality_retrieval import QualityRetrieval,METHODS
from gsearch.quality_protocol import digest,save

ROOT=Path('data/stage26-annotation')


def query_digest(query: dict) -> str:
    return hashlib.sha256(json.dumps(query,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def main():
    if ROOT.exists():raise ValueError('Existing pool must be versioned, not overwritten')
    source=Path('data/stage25-requirements/queries-v2-proposal.json')
    queries=[q for q in json.loads(source.read_text(encoding='utf-8')) if q['inherited_split']=='tuning']
    assert len(queries)==9
    for q in queries:
        assert not q['human_confirmed'] and not q['human_authored']
        q['query_hash']=query_digest(q)
    original_profiles=json.loads(Path('data/stage20-quality/evaluator/profiles-private.json').read_text(encoding='utf-8'))
    profiles={q['source_profile_id']:original_profiles[q['source_profile_id']] for q in queries}
    ROOT.mkdir(parents=True)
    save(ROOT/'inputs/queries.json',queries)
    with threadpool_limits(limits=1):
        started=time.perf_counter();model=Catalog()
        training=pd.read_csv('data/stage9-recommendation/train.csv',dtype={'user_id':str,'arxiv_id':str})
        users={p['user_id'] for p in profiles.values()}
        model.sar=SimpleNamespace(seen=training[training.user_id.isin(users)].groupby('user_id').arxiv_id.agg(set).to_dict())
        model.eligible=lambda user,at:ExpansionRecommender.eligible(model,user,at)
        # Topic-only requests explicitly have no reading-context scoring signal.
        for q in queries:
            q['profile_id']=q['source_profile_id']
            if q['intent']=='topic':
                key='no-reading-context-'+q['source_profile_id']
                profiles[key]={**profiles[q['source_profile_id']],'history_doc_ids':[]}
                q['profile_id']=key
        retriever=QualityRetrieval(model,profiles)
        fit_seconds=time.perf_counter()-started
        runs={m:{} for m in METHODS};raw=[];timings=[]
        for q in queries:
            for method in METHODS:
                started=time.perf_counter();response=retriever.search(q,profiles[q['profile_id']],method)
                timings.append({'query_id':q['query_id'],'method':method,'seconds':time.perf_counter()-started})
                ids=[p['doc_id'] for p in response['papers']]
                assert len(set(ids))==len(ids)<=10 and set(ids).issubset({model.catalog[i] for i in model.eligible(profiles[q['profile_id']]['user_id'],q['at'])})
                runs[method][q['query_id']]=ids
                raw.append({'query_id':q['query_id'],'method':method,'response':response})
            print(json.dumps({'prepared_requests':len(runs['bm25']),'total':9}),flush=True)
        all_docs={d for method in runs.values() for ids in method.values() for d in ids}
        all_docs.update(d for p in profiles.values() for d in p['history_doc_ids'])
        originals={d:ExpansionRecommender.read(model,d,queries[0]['at']) for d in sorted(all_docs)}
        assert all(p['source_verified'] and p['version']==1 for p in originals.values())
        public_fields=('doc_id','version','version_key','title','abstract','source_url','available_at','source_verified')
        paper=lambda d:{k:originals[d][k] for k in public_fields}
        blind={};mapping={}
        for q in queries:
            pool={d for method in runs.values() for d in method[q['query_id']]}
            ids=sorted(pool,key=lambda d:hashlib.sha256(('blind26:'+q['query_id']+':'+d).encode()).hexdigest())
            candidates=[]
            for doc in ids:
                ident='a26-'+hashlib.sha256((q['query_id']+':'+doc).encode()).hexdigest()[:24]
                candidates.append({'annotation_id':ident,'paper':paper(doc)})
                mapping[ident]={'query_id':q['query_id'],'doc_id':doc,'methods':{m:runs[m][q['query_id']].index(doc)+1 for m in METHODS if doc in runs[m][q['query_id']]}}
            public_query={k:q[k] for k in ('query_id','parent_query_id','intent','topic_zh','request','request_zh','required_focus_zh','preferred_focus_zh','grade_2_rule','grade_1_rule','grade_0_rule','query_origin','at','query_hash')}
            context=profiles[q['profile_id']]['history_doc_ids']
            blind[q['query_id']]={'query':public_query,'context':[paper(d) for d in context],'candidates':candidates}
        retriever.searcher.close()
    save(ROOT/'blind/tasks.json',blind)
    save(ROOT/'evaluator/runs.json',runs);save(ROOT/'evaluator/pool-map.json',mapping)
    save(ROOT/'evaluator/raw-results.json',raw)
    save(ROOT/'evaluator/source-originals.json',originals)
    config={'methods':list(METHODS),'personalized_weights':{'query':.7,'context':.3},
        'topic_context':'no history vector; same original all-feedback seen filtering',
        'candidate_order':'hash of query and document, independent of method/rank/score',
        'query_source_sha256':digest(source),'text_signature':model.signature,'human_confirmations':0,'human_labels':0,
        'status':'provisional label-free pool; enable labeling only after same-query human approval',
        'scope':'new revised tuning drafts on old fixed historical catalog; not independent new users or full-catalog recall'}
    save(ROOT/'protocol.json',config)
    immutable={str(p.relative_to(ROOT)):digest(p) for p in ROOT.rglob('*.json')}
    pool_version=query_digest(immutable)
    save(ROOT/'manifest.json',{'pool_version':pool_version,'queries':9,'pairs':len(mapping),'immutable_assets':immutable})
    save(Path('reports/stage26/pool-preparation.json'),{'pool_version':pool_version,'queries':9,'pairs':len(mapping),
        'verified_originals':len(originals),'fit_seconds':fit_seconds,'retrieval_timings':timings,
        'human_labels':0,'ranking_methods':list(METHODS),'provisional':True,'source_sha256':digest(source)})
    print(json.dumps({'status':'unjudged_pool_prepared','queries':9,'pairs':len(mapping),'originals':len(originals),'pool_version':pool_version}),flush=True)


if __name__=='__main__':main()
