"""Full-denominator tuning, using unchanged native metrics and validated scorer."""
import statistics
from pathlib import Path
import time

from gsearch.quality_protocol import digest, save
from gsearch.sid_budget import ROOT, RUNS, ARMS, SEEDS, read
from gsearch.supervision import json_rows, score_rows
from gsearch.supervision_evaluation import evaluate
from gsearch.sid_scoring import accelerated_evaluate


def main() -> None:
    assert read(ROOT/'training-complete.json')['all_six_reference128_gates_passed']
    if (ROOT/'tuning-results.json').exists(): raise FileExistsError('Preserve prior scores')
    protocol=read(ROOT/'protocol.json')
    for name,expected in protocol['files'].items(): assert digest(Path(name))==expected,name
    for name,expected in read(Path('reports/stage44/evaluation-lock.json'))['files'].items():
        assert digest(Path(name))==expected,name
    inputs=Path('data/stage44-supervision')
    labels=list(json_rows(inputs/'tuning.labels.jsonl'))
    profiles={r['user_key']:r for r in json_rows(inputs/'profiles.jsonl')}
    catalog={r['doc_id']:r for r in read(inputs/'catalog.json')}
    popularity=read(inputs/'popularity.json')['counts']
    conditional=[r for r in labels if r['target_doc_id'] in catalog and
                 profiles.get(r['user_key'],{}).get('eligible_train_positive_count',0)>0]
    assert len(labels)==46352 and len(conditional)==1801
    conditional_ids={r['qid'] for r in conditional}
    results={}
    for seed in SEEDS:
        for arm in ARMS:
            name=arm+'-'+str(seed); output=ROOT/(name+'.tuning.score.json')
            if output.exists(): raise FileExistsError('Preserve score '+str(output))
            predictions=list(json_rows(RUNS/name/'tuning.predictions.jsonl'))
            started=time.perf_counter()
            result=accelerated_evaluate(labels,predictions,profiles,catalog,10,popularity)
            # Independent native end-to-end evaluation of a source-fixed512 event slice.
            selected=[labels[i*len(labels)//512] for i in range(512)]
            qids={r['qid'] for r in selected}
            subset=[r for r in predictions if r['qid'] in qids]
            native=evaluate(selected,subset,profiles,catalog,10,popularity)
            fast=accelerated_evaluate(selected,subset,profiles,catalog,10,popularity)
            assert native==fast, 'Native scorer slice mismatch'
            result.update({'protocol_sha256':digest(ROOT/'protocol.json'),
                'run_lock_sha256':digest(ROOT/'run-lock.json'),
                'predictions_sha256':digest(RUNS/name/'tuning.predictions.jsonl'),
                'split':'tuning','optimizer_updates':512,'events':len(labels),
                'evaluation_status':'previously used tuning; no dev or independent-test claim',
                'native512_slice_exact':True,'native_slice_events':len(selected),
                'conditional_diagnostic':score_rows(conditional,[r for r in predictions if r['qid'] in conditional_ids],profiles,catalog,10),
                'scoring_seconds':time.perf_counter()-started})
            save(output,result); results[name]=result
            print({'scored':name,'user_macro':result['user_macro'],'seconds':result['scoring_seconds']},flush=True)
    summary={}
    for arm in ARMS:
        summary[arm]={metric:{'values':[results[arm+'-'+str(s)]['user_macro'][metric] for s in SEEDS],
            'mean':statistics.mean(results[arm+'-'+str(s)]['user_macro'][metric] for s in SEEDS),
            'sample_sd':statistics.stdev(results[arm+'-'+str(s)]['user_macro'][metric] for s in SEEDS)}
            for metric in ['ndcg@10','recall@10','mrr@10']}
    budget_deltas={arm:[results[arm+'-'+str(s)]['user_macro']['ndcg@10']-
        read(Path('reports/stage45')/(arm+'-'+str(s)+'.tuning.score.json'))['user_macro']['ndcg@10'] for s in SEEDS] for arm in ARMS}
    sid_deltas=[results['content-'+str(s)]['user_macro']['ndcg@10']-results['shuffled-'+str(s)]['user_macro']['ndcg@10'] for s in SEEDS]
    save(ROOT/'tuning-results.json', {'scope':'fixed512 steps budget+exposure comparison with bitwise-equivalent128 reference',
        'summary':summary,'budget_ndcg_deltas_512_minus128':budget_deltas,
        'content_minus_shuffled_ndcg512':sid_deltas,'run_scores':{name:digest(ROOT/(name+'.tuning.score.json')) for name in results},
        'primary_denominator':46352,'conditional_diagnostic_denominator':1801,
        'fresh_independent_test':False,'significance_claim':False,'dev_evaluated':False,'rl_started':False})
    print({'summary':summary,'budget_deltas':budget_deltas,'sid_deltas':sid_deltas},flush=True)


if __name__=='__main__': main()
