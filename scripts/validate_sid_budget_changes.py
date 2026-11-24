"""Independent source reconstruction, native conditional scoring and terminal checks."""
from collections import Counter,defaultdict
import csv
import math
from pathlib import Path
import sys

from gsearch.quality_protocol import digest,save
from gsearch.sid_budget_audit import ROOT,DATA,read
from gsearch.supervision import json_rows,score_rows


def close(left: float,right: float) -> None:
    assert abs(left-right)<1e-14,(left,right)


def main() -> None:
    output=ROOT/'validation.json'
    if output.exists():raise FileExistsError('Preserve independent audit validation')
    protocol=read(ROOT/'protocol.json');audit=read(ROOT/'audit.json')
    for name,expected in protocol['files'].items():assert digest(Path(name))==expected,name
    order=read(Path('data/stage45-sft/training-order.json'))['indices']
    pool=list(json_rows(Path('data/stage44-supervision/train.next_item.jsonl')))
    target128=Counter(pool[i]['target_doc_id'] for i in order[:1024]);target512=Counter(pool[i]['target_doc_id'] for i in order[:4096])
    history128=Counter(d for i in order[:1024] for d in pool[i]['history_doc_ids'])
    history512=Counter(d for i in order[:4096] for d in pool[i]['history_doc_ids'])
    items=read(DATA/'item-exposure.json');old_items=read(Path('data/stage46-audit/item-exposure.json'))
    for doc,row in items.items():
        assert row['pilot_label_count']==target128[doc] and row['expanded_label_count']==target512[doc]
        assert row['pilot_history_count']==history128[doc] and row['expanded_history_count']==history512[doc]
        assert all(row[k]==v for k,v in old_items[doc].items())
    def group(doc):
        if doc not in items:return 'outside_catalog'
        if target128[doc]:return 'labelled_first1024'
        if target512[doc]:return 'newly_labelled_1025_4096'
        if items[doc]['full_pool_target_count']:return 'pool_target_still_unselected'
        return items[doc]['group']
    assert audit['coverage']['catalog_groups']==dict(Counter(group(d) for d in items))
    assert audit['coverage']['newly_labelled_papers']==len(set(target512)-set(target128))==2014
    assert audit['coverage']['newly_labelled_papers_already_in1024_history']==len((set(target512)-set(target128))&set(history128))
    labels=list(json_rows(Path('data/stage44-supervision/tuning.labels.jsonl')))
    profiles={r['user_key']:r for r in json_rows(Path('data/stage44-supervision/profiles.jsonl'))}
    catalog={r['doc_id']:r for r in read(Path('data/stage44-supervision/catalog.json'))}
    user_counts=Counter(r['user_key'] for r in labels)
    conditional=[r for r in labels if r['rankable'] and profiles.get(r['user_key'],{}).get('eligible_train_positive_count',0)>0]
    assert len(conditional)==1801
    conditional_ids={r['qid'] for r in conditional}
    cohort_counts=Counter(group(r['target_doc_id']) for r in labels)
    assert dict(cohort_counts)==audit['coverage']['evaluation_target_groups']
    expected_cases={};total_events=total_prefix=0;native=0;checked_changes=0
    known_coverage={}
    with Path('reports/stage48/output-concentration.csv').open(encoding='utf-8-sig',newline='') as handle:
        for row in csv.DictReader(handle):known_coverage[(row['arm']+'-'+row['seed'],row['steps'])]=row
    for run,result in audit['runs'].items():
        arm=run.split('-')[0];mapping=read(Path('data/stage45-sft')/(arm+'.tokens.json'))
        preds={};raw={}
        for budget,stage in [(128,'stage45'),(512,'stage48')]:
            rows=list(json_rows(Path('runs')/stage/run/'tuning.predictions.jsonl'))
            preds[budget]={r['qid']:r['doc_ids'] for r in rows}
            assert len(rows)==len(preds[budget])==46352
            raw[budget]=read(Path('runs')/stage/run/'raw-user-decoding.json')
            selected=[r for r in rows if r['qid'] in conditional_ids]
            values=score_rows(conditional,selected,profiles,catalog,10)
            actual=result['metrics'][str(budget)]['rankable_with_context']
            assert values['events']==actual['events'] and values['users']==actual['users']
            for scope in ['user_macro','event_micro']:
                for metric,value in values[scope].items():close(value,actual[scope][metric])
            native+=1
            unique={d for r in raw[budget].values() if not r['fallback'] for d in r['doc_ids']}
            tops=Counter(r['doc_ids'][0] for r in raw[budget].values() if not r['fallback'])
            observed=result['output'][str(budget)]
            prior=known_coverage[(run,str(budget))]
            assert observed['unique_papers']==len(unique)==int(prior['unique_top10_papers'])
            close(observed['top1_max_share'],max(tops.values())/2128)
            close(observed['top1_max_share'],float(prior['top1_max_share']))
            slots=Counter(d for r in raw[budget].values() if not r['fallback'] for d in r['doc_ids'])
            close(observed['source_likes_slot_mean'],sum(n*items[d]['source_train_likes'] for d,n in slots.items())/21280)
            for depth,prefix_row in enumerate(observed['prefix'],1):
                pc=Counter(tuple(mapping[d][:depth]) for d,n in slots.items() for _ in range(n))
                assert prefix_row['unique_output_prefixes']==len(pc)
                close(prefix_row['largest_output_prefix_share'],max(pc.values())/21280)
        saved={r['qid']:r for r in json_rows(DATA/(run+'.changes.jsonl'))}
        terminal={r['qid']:r for r in json_rows(DATA/(run+'.terminal-prefix.jsonl'))}
        assert len(terminal)==1801
        cohorts=defaultdict(Counter);deltas=defaultdict(float);positive=defaultdict(float);negative=defaultdict(float)
        changed_ids=set();prefix_counts={128:Counter(),512:Counter()};user_gain=defaultdict(float);paper_gain=defaultdict(float);user_net=defaultdict(float)
        for label in labels:
            qid=label['qid'];u=label['user_key'];d=label['target_doc_id'];cohort=group(d)
            has_context=profiles.get(u,{}).get('eligible_train_positive_count',0)>0
            availability=('unrankable:'+str(label['miss_reason'])) if not label['rankable'] else ('rankable_with_context' if has_context else 'rankable_without_context')
            a=preds[128][qid];b=preds[512][qid]
            r0=a.index(d)+1 if d in a else None;r1=b.index(d)+1 if d in b else None
            kind=('both_miss' if r1 is None else 'new_hit') if r0 is None else ('lost_hit' if r1 is None else 'retained_up' if r1<r0 else 'retained_down' if r1>r0 else 'retained_same')
            n0=1/math.log2(r0+1) if r0 else 0.;n1=1/math.log2(r1+1) if r1 else 0.
            change=(n1-n0)/(3571*user_counts[u])
            groups=['full',availability,'exposure:'+cohort]
            if availability=='rankable_with_context':groups+=['context_exposure:'+cohort]
            for key in groups:
                cohorts[key][kind]+=1;deltas[key]+=change;positive[key]+=max(change,0);negative[key]-=min(change,0)
            if kind not in ['both_miss','retained_same']:
                changed_ids.add(qid);row=saved[qid]
                assert row['transition']==kind and row['old_rank']==r0 and row['new_rank']==r1
                assert row['user_key']==u and row['target_doc_id']==d and row['exposure']==cohort
                close(row['weighted_delta']['ndcg'],change)
                assert row['target_source_likes']==items[d]['source_train_likes']
                assert row['target_old_labels']==target128[d] and row['target_new_labels']==target512[d]
                assert row['target_first1024_history_count']==history128[d]
                assert row['added_papers']==[x for x in b if x not in a]
                assert row['added_source_likes']==[items[x]['source_train_likes'] for x in row['added_papers']]
                key=run+':'+kind+':'+cohort
                if key not in expected_cases or qid<expected_cases[key]['qid']:expected_cases[key]=label
                user_net[u]+=change
                if change>0:user_gain[u]+=change;paper_gain[d]+=change
                checked_changes+=1
            if availability=='rankable_with_context':
                pair=terminal[qid]
                for budget,rank,field in [(128,r0,'old_prefix'),(512,r1,'new_prefix')]:
                    paths=raw[budget][u]['token_ids'];target=mapping[d]
                    present=[tuple(target[:depth]) in {tuple(p[:depth]) for p in paths} for depth in range(1,5)]
                    observed=pair[field]
                    assert observed['prefix_covered']==present and not observed['actual_beam_pruning_step_observed']
                    assert (rank is not None)==present[-1]
                    missing=None if rank else next(depth for depth,yes in enumerate(present,1) if not yes)
                    assert observed['first_missing_final_prefix_depth']==missing
                    prefix_counts[budget]['events']+=1;prefix_counts[budget]['hits']+=int(rank is not None)
                    if missing is not None:prefix_counts[budget]['missing_'+str(missing)]+=1
                    for depth,yes in enumerate(present,1):prefix_counts[budget]['covered_'+str(depth)]+=int(yes)
                    total_prefix+=1
            total_events+=1
        assert set(saved)==changed_ids
        for group,counts in cohorts.items():
            actual=result['changes'][group]
            assert actual['events']==sum(counts.values())
            assert all(actual['transitions'][k]==counts[k] for k in actual['transitions'])
            close(actual['weighted_ndcg_delta'],deltas[group]);close(actual['gross_positive_ndcg'],positive[group]);close(actual['gross_negative_ndcg'],negative[group])
        for b in [128,512]:assert dict(prefix_counts[b])==result['terminal_prefix'][str(b)]
        for counts,field in [(user_gain,'top1_user_share_of_gross_positive'),(paper_gain,'top1_paper_share_of_gross_positive')]:
            expected=max(counts.values())/sum(counts.values()) if counts else None
            if expected is None:assert result['concentration'][field] is None
            else:close(result['concentration'][field],expected)
        assert result['concentration']['positive_net_users']==sum(v>1e-15 for v in user_net.values())
        assert result['concentration']['negative_net_users']==sum(v< -1e-15 for v in user_net.values())
    cases=read(DATA/'cases.json');assert len(cases)==len(expected_cases)
    assert {c['case_type'] for c in cases}==set(expected_cases)
    for case in cases:
        label=expected_cases[case['case_type']];d=label['target_doc_id']
        assert case['qid']==label['qid'] and case['target_doc_id']==d
        assert case['target_metadata']=={k:catalog[d][k] for k in ['title','abstract','version_key','source_url']}
        for budget,stage in [('128','stage45'),('512','stage48')]:
            trace=read(Path('runs')/stage/case['run']/'raw-user-decoding.json')[label['user_key']]
            assert case['traces'][budget]==trace
    assert 'torch' not in sys.modules and 'transformers' not in sys.modules
    save(output,{'status':'passed','source_item_counts':9000,'source_exposure_samples':4096,
        'paired_full_event_checks':total_events,'independent_terminal_prefix_checks':total_prefix,
        'native_conditional_metric_checks':native,'changed_event_records_verified':checked_changes,
        'case_selection_and_v1_metadata_checks':len(cases),'unchanged_stage48_output_summaries':12,
        'full_denominator_weighted_delta_rebuilt':True,'torch_loaded':False,'new_training_or_generation':False})
    print(read(output),flush=True)


if __name__=='__main__':main()
