"""Reproduce the sealed nine-query retrieval; inspect contributions without tuning."""
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
from sklearn.metrics.pairwise import linear_kernel
from sklearn.preprocessing import normalize
from threadpoolctl import threadpool_limits

from gsearch.expansion_recommendation import ExpansionRecommender
from gsearch.quality_protocol import save
from gsearch.quality_retrieval import METHODS, QualityRetrieval
from gsearch.visitor_profile import Catalog

ROOT = Path('data/stage28-coverage')


def load(path: str) -> object:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main() -> None:
    output = ROOT/'retrieval-replay.json'
    if output.exists(): raise ValueError('Preserve previous diagnostic replay')
    queries = [q for q in load('data/stage26-annotation/inputs/queries.json')]
    assert len(queries) == 9
    profiles = load('data/stage20-quality/evaluator/profiles-private.json')
    original = load('data/stage26-annotation/evaluator/runs.json')
    diagnostics = []
    with threadpool_limits(limits=1):
        model = Catalog()
        train = pd.read_csv('data/stage9-recommendation/train.csv', dtype={'user_id':str,'arxiv_id':str})
        user_ids = {profiles[q['source_profile_id']]['user_id'] for q in queries}
        model.sar = SimpleNamespace(seen=train[train.user_id.isin(user_ids)].groupby('user_id').arxiv_id.agg(set).to_dict())
        model.eligible = lambda user,at: ExpansionRecommender.eligible(model,user,at)
        for q in queries:
            q['profile_id'] = q['source_profile_id']
            if q['intent'] == 'topic':
                key = 'no-reading-context-'+q['source_profile_id']
                profiles[key] = {**profiles[q['source_profile_id']], 'history_doc_ids':[]}
                q['profile_id'] = key
        retrieval = QualityRetrieval(model,profiles)
        try:
            for q in queries:
                p = profiles[q['profile_id']]
                results = {}
                for method in METHODS:
                    response = retrieval.search(q,p,method)
                    ids = [r['doc_id'] for r in response['papers']]
                    assert ids == original[method][q['query_id']], (q['query_id'],method)
                    results[method] = response
                query_vector = model.vectorizer.transform([q['request']])
                context_vector = retrieval.contexts[q['profile_id']]
                query_scores = linear_kernel(query_vector,model.documents).ravel()
                context_scores = linear_kernel(context_vector,model.documents).ravel()
                mixed_raw = .7*query_vector.toarray()+.3*context_vector
                norm = np.linalg.norm(mixed_raw)
                rows = []
                for rank,paper in enumerate(results['personalized_query_tfidf']['papers'],1):
                    doc = paper['doc_id']; i = model.position[doc]
                    has_context = bool(np.any(context_vector))
                    q_part = float(.7*query_scores[i]/norm) if has_context else float(query_scores[i])
                    c_part = float(.3*context_scores[i]/norm) if has_context else 0.0
                    assert np.isclose(q_part+c_part,paper['score'],rtol=1e-9,atol=1e-12)
                    query_ids = [v['doc_id'] for v in results['query_tfidf']['papers']]
                    rows.append({'doc_id':doc,'title':paper['title'],'mixed_rank':rank,
                        'query_only_top10_rank':query_ids.index(doc)+1 if doc in query_ids else None,
                        'score':paper['score'],'actual_query_contribution':q_part,
                        'actual_history_contribution':c_part,
                        'history_score_fraction':c_part/paper['score'],
                        'primary_category':model.by_id[doc]['primary_category'],
                        'source_url':paper['source_url']})
                tracked = []
                for doc in ['1506.08839','2411.03965','2402.18166','2412.05543','2311.07396']:
                    if doc not in model.position:continue
                    i=model.position[doc]
                    eligible = model.eligible(p['user_id'],q['at'])
                    permitted = bool(np.any(eligible==i))
                    # Native query-TFIDF scores and stable order, all eligible documents.
                    positive = eligible[query_scores[eligible]>0]
                    ordered = positive[np.argsort(-query_scores[positive],kind='stable')]
                    position = np.flatnonzero(ordered==i)
                    tracked.append({'doc_id':doc,'eligible':permitted,'seen':doc in model.sar.seen.get(p['user_id'],set()),
                        'query_tfidf_score':float(query_scores[i]),
                        'query_tfidf_positive_rank':int(position[0]+1) if len(position) else None})
                diagnostics.append({'query_id':q['query_id'],'intent':q['intent'],'reproduction_passed':True,
                    'available_count':int(np.count_nonzero(model.available <= __import__('datetime').datetime.fromisoformat(q['at']).timestamp())),
                    'eligible_count':len(model.eligible(p['user_id'],q['at'])),
                    'methods':results,'mixed_score_decomposition':rows,'illustrative_partial_papers':tracked})
                print(json.dumps({'reproduced_query':q['query_id'],'methods_matching':3}),flush=True)
        finally:
            retrieval.searcher.close()
    save(output, {'scope':'post-stage27 diagnostic unblinding; original results frozen before inspection',
        'native_replays_matching':27,'parameters_changed':False,'quality_metrics_computed':False,
        'text_signature':model.signature,'queries':diagnostics})
    print(json.dumps({'replayed_matching':27,'contribution_decompositions':sum(len(q['mixed_score_decomposition']) for q in diagnostics),
        'six_context_queries_top10_history_share':{q['query_id']:round(float(np.mean([r['history_score_fraction'] for r in q['mixed_score_decomposition']])),4)
            for q in diagnostics if q['intent']!='topic'}},ensure_ascii=False))


if __name__ == '__main__':main()
