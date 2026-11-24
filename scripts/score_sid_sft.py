"""Apply the sealed stage44 scorer to all predeclared tuning comparisons."""
import json
from pathlib import Path
import statistics
import sys

from gsearch.quality_protocol import digest, save
from scripts.score_supervision import main as score


def main() -> None:
    report=Path('reports/stage45')
    if (report/'tuning-results.json').exists():raise FileExistsError('Preserve all scores')
    runs=[]
    for method in ['popular','content','sar']:
        runs.append((method,Path('data/stage45-sft')/(method+'.tuning.predictions.jsonl'),None))
    for seed in [42,2024,3407]:
        for arm in ['content','shuffled']:
            runs.append((arm+'-'+str(seed),Path('runs/stage45')/(arm+'-'+str(seed))/'tuning.predictions.jsonl',seed))
    results={}
    for name,predictions,seed in runs:
        output=report/(name+'.tuning.score.json')
        sys.argv=['score_supervision','--split','tuning','--run-lock',str(report/'run-lock.json'),
                  '--predictions',str(predictions),'--output',str(output)]
        score()
        result=json.loads(output.read_text(encoding='utf-8'))
        results[name]={'seed':seed,'user_macro':result['user_macro'],'event_micro':result['event_micro'],
            'groups':result['groups'],'events':result['events'],'users':result['users'],
            'valid_slot_rate':result['valid_slot_rate'],'duplicate_slot_rate':result['duplicate_slot_rate'],
            'score_sha256':digest(output)}
    summary={}
    for arm in ['content','shuffled']:
        values=[results[arm+'-'+str(seed)]['user_macro'] for seed in [42,2024,3407]]
        summary[arm]={metric:{'mean':statistics.mean(v[metric] for v in values),
                              'sample_sd':statistics.stdev(v[metric] for v in values),
                              'values':[v[metric] for v in values]} for metric in values[0]}
    deltas=[results['content-'+str(s)]['user_macro']['ndcg@10']-results['shuffled-'+str(s)]['user_macro']['ndcg@10']
            for s in [42,2024,3407]]
    save(report/'tuning-results.json',{'scope':'fixed128-step local pilot; reused tuning, no descriptive dev read; not a full MiniOneRec reproduction',
        'run_lock_sha256':digest(report/'run-lock.json'),'all_comparisons':results,'three_seed_summary':summary,
        'paired_content_minus_shuffled_ndcg':deltas,'paired_mean_delta':statistics.mean(deltas),
        'fresh_independent_test':False,'significance_claim':False,'dev_evaluated':False})
    print({'summary':summary,'paired_ndcg_deltas':deltas},flush=True)


if __name__=='__main__':main()
