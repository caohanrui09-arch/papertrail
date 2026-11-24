"""Independent label scans, probability normalization and archived-loss comparison."""
from collections import Counter,defaultdict
import csv
import json
import math
from pathlib import Path
import sys

from gsearch.quality_protocol import digest,save
from gsearch.sid_prefix_prior import ROOT,DATA,read


def rows(path: Path):
    with path.open(encoding='utf-8') as handle:
        for line in handle:
            if line.strip():yield json.loads(line)


def close(a: float,b: float) -> None:
    assert abs(a-b)<1e-12,(a,b)


def main() -> None:
    target=ROOT/'validation.json'
    if target.exists():raise FileExistsError('Preserve independent validation')
    protocol=read(ROOT/'protocol.json')
    for name,expected in protocol['files'].items():assert digest(Path(name))==expected,name
    samples=read(Path('data/stage50-health/prefixes.json'));source_samples={r['sample_id']:r for r in samples}
    metadata={r['sample_id']:r for r in read(Path('data/stage50-health/prefix-exposure.json'))}
    marginal=read(Path('data/stage50-health/position-priors.json'));queries={}
    normalized=0;query_checks=0
    for arm in ['content','shuffled']:
        labels=[r['labels'] for r in rows(Path('data/stage48-budget')/(arm+'.ordered.jsonl'))]
        assert len(labels)==4096
        mapping=read(Path('data/stage45-sft')/(arm+'.tokens.json'));tables=read(DATA/(arm+'.prefix-counts.json'))
        assert len(tables)==5
        for pos,level in enumerate(tables):
            allowed=sorted({tokens[pos] for tokens in mapping.values()})
            assert level['allowed_ids']==allowed and level['alpha']==1 and level['position']==pos
            expected=defaultdict(Counter)
            for label in labels:expected[tuple(label[:pos])][label[pos]]+=1
            assert len(level['contexts'])==len(expected)
            for key,value in level['contexts'].items():
                prefix=tuple(json.loads(key));counts=expected[prefix]
                assert value['total']==sum(counts.values())
                assert value['label_counts']=={str(t):n for t,n in counts.items()}
                denominator=sum(counts.values())+len(allowed)
                close(sum((counts[t]+1)/denominator for t in allowed),1)
                normalized+=1
            assert sum(c['total'] for c in level['contexts'].values())==4096
        arm_queries=list(rows(DATA/(arm+'.queries.jsonl')))
        assert len(arm_queries)==160
        queries[arm]={(r['sample_id'],r['position_index']):r for r in arm_queries}
        assert len(queries[arm])==160
        for query in arm_queries:
            sid=query['sample_id'];pos=query['position_index'];sample=source_samples[sid]
            gold=mapping[sample['target_doc_id']];prefix=gold[:pos];next_token=gold[pos]
            assert query['prefix_ids']==prefix and query['target_token_id']==next_token
            assert query['history_length']==sample['history_length']
            assert all(query[k]==v for k,v in metadata[sid].items())
            matching=[label for label in labels if label[:pos]==prefix]
            counts=Counter(label[pos] for label in matching);k=len(tables[pos]['allowed_ids'])
            expected=math.log(len(matching)+k)-math.log(counts[next_token]+1)
            expected_marginal=math.log(4096+k)-math.log(sum(label[pos]==next_token for label in labels)+1)
            close(query['prefix_nll'],expected);close(query['marginal_nll'],expected_marginal)
            assert query['context_total']==len(matching) and query['target_count']==counts[next_token]
            assert query['context_seen']==bool(matching) and query['codebook_size']==k
            if not matching:close(query['prefix_nll'],math.log(k))
            if pos==0:close(query['prefix_nll'],query['marginal_nll'])
            if pos==4:close(query['prefix_nll'],0)
            close(sum((counts[t]+1)/(len(matching)+k) for t in tables[pos]['allowed_ids']),1)
            query_checks+=1
    comparison=read(ROOT/'comparison.json');runs=comparison['summary'];records_by_run={};model_values=0
    for run in runs:
        arm=run.split('-')[0]
        raw_old=read(Path('data/stage50-health')/run/'reference128-rescored.json')['samples']
        raw_new=read(Path('data/stage50-health')/run/'position-loss.json')['samples']
        old={r['sample_id']:r for r in raw_old};new={r['sample_id']:r for r in raw_new}
        records=list(rows(DATA/(run+'.comparison.jsonl')))
        assert len(records)==160 and len({(r['sample_id'],r['position_index']) for r in records})==160
        for record in records:
            sid=record['sample_id'];pos=record['position_index'];query=queries[arm][(sid,pos)]
            assert all(record[k]==v for k,v in query.items())
            assert record['model128_nll']==old[sid]['positions'][pos]['position_conditional_nll']
            assert record['model512_nll']==new[sid]['positions'][pos]['position_conditional_nll']
            model_values+=2
        records_by_run[run]=records
    aggregate_count=0
    with (ROOT/'four-method-comparison.csv').open(encoding='utf-8-sig',newline='') as handle:
        for row in csv.DictReader(handle):
            records=records_by_run[row['run']];group_name=row['group'];name=row['position']
            if group_name!='all':
                if group_name.startswith('event:'):records=[r for r in records if r['event_exposure']==group_name.split(':',1)[1]]
                elif group_name.startswith('paper:'):records=[r for r in records if r['target_paper_exposure']==group_name.split(':',1)[1]]
                else:records=[r for r in records if r['history_length']==int(group_name.removeprefix('history'))]
            chosen=[r for r in records if r['position_index']<3] if name=='semantic_mean' else [r for r in records if r['position']==name]
            assert int(row['token_records'])==len(chosen) and int(row['samples'])==len({r['sample_id'] for r in chosen})
            for field in ['marginal_nll','prefix_nll','model128_nll','model512_nll','uniform_nll']:
                close(float(row[field]),math.fsum(r[field] for r in chosen)/len(chosen))
            assert int(row['unseen_prefix_records'])==sum(not r['context_seen'] for r in chosen)
            close(float(row['model512_minus_prefix_nll']),float(row['model512_nll'])-float(row['prefix_nll']))
            aggregate_count+=1
    assert aggregate_count==288
    beats=[]
    for run,summary in runs.items():
        semantic=[r for r in records_by_run[run] if r['position_index']<3]
        for field in ['marginal_nll','prefix_nll','model128_nll','model512_nll']:
            close(summary[field],math.fsum(r[field] for r in semantic)/96)
        if summary['model512_nll']<summary['prefix_nll']-1e-12:beats.append(run)
    decision=read(ROOT/'decision.json')
    assert decision['model512_runs_beating_prefix_prior']==beats and decision['closure_condition_met']==(not beats)
    assert not decision['personalization_proven'] and not decision['new_training_started'] and not decision['new_decode_or_model_forward']
    assert query_checks==320 and model_values==1920
    assert 'torch' not in sys.modules and 'transformers' not in sys.modules
    save(target,{'status':'passed','label_sequences_per_mapping':4096,'prefix_queries_independent_scan':query_checks,
        'observed_context_distributions_normalized':normalized,'archived_model_position_losses_checked':model_values,
        'wide_position_comparison_records':960,'group_position_aggregate_rows':aggregate_count,
        'unchanged_strict_prefixes':32,'first_position_equals_marginal':True,'unseen_context_uniform':True,
        'full_position_codebook_matches_model':True,'no_model_load_forward_generate':True,
        'closure_decision_reproduced':True})
    print(read(target),flush=True)


if __name__=='__main__':main()
