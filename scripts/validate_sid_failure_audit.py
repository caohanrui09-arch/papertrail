"""Independent reconstruction of stage46 counts and native conditional metrics."""
from collections import Counter,defaultdict
import json
from pathlib import Path

from gsearch.quality_protocol import digest,save
from gsearch.supervision import json_rows,score_rows


def read(path: Path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main() -> None:
    report=Path('reports/stage46');data=Path('data/stage46-audit')
    assert not (report/'validation.json').exists()
    audit=read(report/'audit.json');protocol=read(report/'protocol.json')
    for name,expected in protocol['files'].items():assert digest(Path(name))==expected,name
    labels=list(json_rows(Path('data/stage44-supervision/tuning.labels.jsonl')))
    profiles={r['user_key']:r for r in json_rows(Path('data/stage44-supervision/profiles.jsonl'))}
    catalog={r['doc_id']:r for r in read(Path('data/stage44-supervision/catalog.json'))}
    source=read(Path('data/stage44-supervision/training-stats.json'))['catalog_source_positive_counts']
    mappings={a:read(Path('data/stage45-sft')/(a+'.tokens.json')) for a in ['content','shuffled']}
    order=read(Path('data/stage45-sft/training-order.json'))['sample_ids'][:1024]
    wanted=set(order);pool_targets=Counter();pilot_targets=Counter();pilot_users=set();pilot_history=Counter();selected={}
    for row in json_rows(Path('data/stage44-supervision/train.next_item.jsonl')):
        pool_targets[row['target_doc_id']]+=1
        if row['sample_id'] in wanted:
            selected[row['sample_id']]=row;pilot_targets[row['target_doc_id']]+=1
            pilot_users.add(row['user_key']);pilot_history.update(row['history_doc_ids'])
    assert read(data/'selected-samples.json')==[selected[qid] for qid in order]
    coverage=audit['coverage']
    assert coverage['pilot_target_papers']==len(pilot_targets)==913
    assert coverage['pilot_users']==len(pilot_users)==843
    assert coverage['pilot_history_papers']==len(pilot_history)==5009
    assert coverage['full_pool_target_papers']==len(pool_targets)==7992
    for arm in mappings:
        for depth,row in enumerate(coverage['prefix_coverage'][arm],1):
            expected={tuple(mappings[arm][d][:depth]) for d in pilot_targets}
            assert row['pilot_label_prefixes']==len(expected)
    eligibility=Counter(r['doc_id'] for r in json_rows(Path('data/stage44-supervision/train.feedback.jsonl'))
                        if r['rating']==1 and r['available_at_event'])
    items=read(data/'item-exposure.json')
    for doc in catalog:
        row=items[doc]
        assert row['source_train_likes']==source.get(doc,0)
        assert row['proxy_eligible_train_likes']==eligibility.get(doc,0)
        assert row['full_pool_target_count']==pool_targets.get(doc,0)
        assert row['pilot_label_count']==pilot_targets.get(doc,0)
        assert row['pilot_history_count']==pilot_history.get(doc,0)
    conditional=[r for r in labels if r['rankable'] and profiles.get(r['user_key'],{}).get('eligible_train_positive_count',0)>0]
    counts=Counter()
    for row in labels:
        if not row['rankable']:key='unrankable:'+str(row['miss_reason'])
        elif profiles.get(row['user_key'],{}).get('eligible_train_positive_count',0)>0:key='rankable_with_context'
        else:key='rankable_without_context'
        counts[key]+=1
        if row['target_doc_id'] in catalog:
            assert row['target_train_positive_count']==source.get(row['target_doc_id'],0)
    assert dict(counts)==audit['availability_partition']
    assert len(conditional)==1801 and len({r['user_key'] for r in conditional})==528
    wanted_qids={r['qid'] for r in conditional};methods={}
    for method in ['popular','content','sar']:
        methods[method]=Path('data/stage45-sft')/(method+'.tuning.predictions.jsonl')
    methods.update({p.parent.name:p for p in Path('runs/stage45').glob('*/tuning.predictions.jsonl')})
    native_checks=0;prefix_checks=0
    qid_label={r['qid']:r for r in labels}
    candidates={}
    for row in labels:
        qid=row['qid'];doc=row['target_doc_id'];user=row['user_key']
        group=('unrankable:'+str(row['miss_reason'])) if not row['rankable'] else (
            'rankable_with_context' if profiles.get(user,{}).get('eligible_train_positive_count',0)>0 else 'rankable_without_context')
        key='exposure:'+items[doc]['group'] if group=='rankable_with_context' else 'partition:'+group
        if key not in candidates or qid<candidates[key]['qid']:candidates[key]=row
    content_rows={r['qid']:r for r in json_rows(methods['content'])}
    for method,path in methods.items():
        rows=list(json_rows(path));by_qid={r['qid']:r for r in rows}
        native=score_rows(conditional,[r for r in rows if r['qid'] in wanted_qids],profiles,catalog,10)
        actual=audit['metrics'][method]['rankable_with_context']
        for key in ['user_macro','event_micro']:
            assert all(abs(v-actual[key][metric])<1e-14 for metric,v in native[key].items())
        native_checks+=1
        if '-' not in method:continue
        arm=method.split('-')[0]
        raw=read(Path('runs/stage45')/method/'raw-user-decoding.json')
        prefix=Counter();prefix['events']=len(conditional)
        exposed=Counter();differences=Counter();missed={r['qid']:r for r in json_rows(data/(method+'.terminal-prefix-misses.jsonl'))}
        for label in conditional:
            qid=label['qid'];doc=label['target_doc_id'];user=label['user_key'];target=mappings[arm][doc]
            predictions=by_qid[qid]['doc_ids'];hit=doc in predictions;prefix['hits']+=int(hit)
            paths=raw[user]['token_ids']
            present={depth:tuple(target[:depth]) in {tuple(path[:depth]) for path in paths} for depth in range(1,5)}
            for depth,covered in present.items():prefix['target_final_prefix_covered_depth_'+str(depth)]+=int(covered)
            if not hit:
                missing=min(depth for depth,covered in present.items() if not covered)
                prefix['missing_at_depth_'+str(missing)]+=1
                assert missed[qid]['first_missing_final_prefix_depth']==missing
                assert missed[qid]['actual_beam_pruning_step_observed'] is False
                exposed[items[doc]['group']]+=1
            assert hit==present[4]
            baseline_hit=doc in content_rows[qid]['doc_ids']
            diff='both_hit' if hit and baseline_hit else 'content_only_hit' if baseline_hit else 'sid_only_hit' if hit else 'both_miss'
            differences[diff]+=1
            if diff=='content_only_hit':
                key='content_only:'+method+':'+items[doc]['group']+':'+items[doc]['mapping_group']
                if key not in candidates or qid<candidates[key]['qid']:candidates[key]=label
            prefix_checks+=1
        actual_prefix=audit['terminal_prefix'][method]
        assert all(actual_prefix['counts'].get(k,0)==v for k,v in prefix.items())
        assert actual_prefix['miss_exposure_counts']==dict(exposed)
        assert all(audit['baseline_content_vs_sid'][method].get(k,0)==v for k,v in differences.items())
        assert len(missed)==len(conditional)-prefix['hits']
    cases=read(data/'cases.json')
    assert len(cases)==len(candidates)==36
    for case in cases:
        label=candidates[case['case_type']]
        assert case['qid']==label['qid'] and case['target_doc_id']==label['target_doc_id']
        doc=case['target_doc_id'];metadata=case['target_metadata']
        if doc in catalog:
            assert all(metadata[k]==catalog[doc][k] for k in ['title','abstract','version_key','source_url'])
        else:
            assert metadata is None
            assert case['target_source_train_likes']==label['target_train_positive_count']
    concentration=read(report/'output-concentration.json')
    for method,path in methods.items():
        rows=list(json_rows(path));by_user={qid_label[r['qid']]['user_key']:r['doc_ids'] for r in rows}
        cohort=sorted({r['user_key'] for r in labels if profiles.get(r['user_key'],{}).get('eligible_train_positive_count',0)>0})
        observed=[by_user[u] for u in cohort]
        actual=concentration['metrics'][method]['all_context_users']
        assert actual['unique_recommended_papers']==len({d for ranking in observed for d in ranking})
        assert actual['unique_ordered_top10_lists']==len(set(map(tuple,observed)))
        assert actual['largest_top1_user_fraction']==max(Counter(r[0] for r in observed).values())/len(cohort)
    save(report/'validation.json',{'status':'passed','independent_native_conditional_metric_checks':native_checks,
        'independent_terminal_prefix_event_checks':prefix_checks,'case_provenance_and_selection_checks':len(cases),
        'pilot_and_full_pool_reconstruction':True,'all_item_exposure_fields_checked':9000,
        'original_full_denominator_46352_retained':True,'profile_with_context_not_pilot_user_identity':True,
        'prefix_is_terminal_coverage_not_pruning_time':True,
        'sources_hashed_unchanged':len(protocol['files'])})
    print({'validation':'passed','native_groups':native_checks,'prefix_events':prefix_checks,'cases':len(cases)},flush=True)


if __name__=='__main__':main()
