"""Human-gated pool evaluation, directly reusing retained native_scores."""
from research73.common import DATA,read


def algorithm_report(store,owner: str) -> dict:
    from gsearch.human_quality import native_scores
    mapping=read(DATA/'private/pool-map.json');runs=read(DATA/'runs/top10.json')
    labels={};complete=[];approved=[];empty=[]
    for qid in store.pool.tasks:
        detail=store.detail(owner,qid);review=detail['review'].get('value') or {}
        human_review=review.get('origin')=='human' and review.get('status')=='approve'
        if human_review:approved.append(qid)
        ids=[]
        for c in detail['candidates']:
            ids.append(c['annotation_id']);value=c['record'].get('value') or {}
            if human_review and c['valid_submission'] and value.get('origin')=='human' and value.get('attested'):
                labels[c['annotation_id']]=value['grade']
        if not ids:empty.append(qid)
        elif human_review and all(i in labels for i in ids):complete.append(qid)
    qrels={qid:{item['doc_id']:labels[aid] for aid,item in mapping.items() if item['query_id']==qid} for qid in complete}
    scores={method:native_scores(qrels,{q:rows[q] for q in complete}) for method,rows in runs.items()} if complete else None
    return {'protocol':'stage73-v1','human_submitted_pairs':len(labels),'total_pairs':len(mapping),
            'human_confirmed_queries':len(approved),'complete_queries':complete,'total_queries':len(store.pool.tasks),
            'empty_candidate_queries':empty,'coverage':len(labels)/len(mapping) if mapping else 0,
            'quality_scores':scores,'quality_status':'暂不可计算：没有完整真人确认与标注的候选池' if scores is None else '仅完整真人标注的池内查询子集',
            'scope':'complete human-judged pooled subset only; no independent-test or full-catalog recall claim',
            'unjudged_as_zero':False,'full_catalog_recall':None,'model_judgments_counted_as_human':False,
            'auxiliary_model_judgments':len(read(DATA/'auxiliary/model-judgments.json'))}
