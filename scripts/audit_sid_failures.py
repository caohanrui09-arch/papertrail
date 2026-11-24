"""Stage46: reuse stage44/45 only; no torch/model load, fit or generate."""
from collections import Counter,defaultdict
import csv
import json
from pathlib import Path
import time

from gsearch.quality_protocol import digest,save
from gsearch.sid_failure_audit import (MetricAccumulator,exposure_group,availability_group,
    mapping_group,final_prefix_status,prefix_coverage)
from gsearch.supervision import json_rows

REPORT=Path('reports/stage46');DATA=Path('data/stage46-audit')


def read(path: Path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write_csv(path: Path,rows: list[dict]) -> None:
    with path.open('x',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def predictions_by_user(path: Path,labels: list[dict]) -> dict:
    expected={r['qid']:r['user_key'] for r in labels};seen=set();result={}
    for row in json_rows(path):
        qid=row['qid']
        if qid not in expected or qid in seen:raise ValueError('Bad prediction event coverage')
        seen.add(qid);user=expected[qid]
        if user in result and result[user]!=row['doc_ids']:raise ValueError('Fixed profile changed')
        result[user]=row['doc_ids']
    if seen!=set(expected):raise ValueError('Incomplete predictions')
    return result


def main() -> None:
    REPORT.mkdir(parents=True,exist_ok=True);DATA.mkdir(parents=True,exist_ok=True)
    if (REPORT/'audit.json').exists():raise FileExistsError('Preserve completed audit')
    start=time.perf_counter()
    paths=[Path('reports/stage45/final-validation-v2.json'),Path('reports/stage45/run-lock.json'),
        Path('data/stage44-supervision/catalog.json'),Path('data/stage44-supervision/train.next_item.jsonl'),
        Path('data/stage44-supervision/train.feedback.jsonl'),Path('data/stage44-supervision/profiles.jsonl'),
        Path('data/stage44-supervision/training-stats.json'),Path('data/stage44-supervision/tuning.labels.jsonl'),
        Path('data/stage45-sft/training-order.json'),Path('data/stage45-sft/content.tokens.json'),
        Path('data/stage45-sft/shuffled.tokens.json')]
    paths.extend(Path('data/stage45-sft')/(m+'.tuning.predictions.jsonl') for m in ['popular','content','sar'])
    paths.extend(p for p in Path('runs/stage45').glob('*/raw-user-decoding.json'))
    paths.extend(p for p in Path('runs/stage45').glob('*/tuning.predictions.jsonl'))
    paths.extend(Path('reports/stage45').glob('*.tuning.score.json'))
    paths.extend([Path('gsearch/sid_failure_audit.py'),Path('scripts/audit_sid_failures.py'),
                  Path('gsearch/evaluate.py'),Path('gsearch/sid_sft.py')])
    protocol={'frozen_before_audit_computations':True,'scope':'posthoc descriptive tuning audit, no fresh independent test',
        'old_receipt_sha256':'2e7bf16a10f196f42cde8ce2bd75055f3e611951b3ecbbcef73d91d879bf0949',
        'metric':'unchanged gsearch.evaluate.metrics; average events within user then users; conditional groups secondary only',
        'source_item_cold':'zero original train positives, distinct from proxy-eligible positives, next-item pool and pilot exposure',
        'availability_partition':'outside/other-unrankable/rankable without context/rankable with context; full denominator retained',
        'exposure_partition':['no_source_train_like','train_liked_without_proxy_eligible_feedback',
            'eligible_like_without_next_item_target','pool_target_not_selected_in_pilot','pilot_target_seen'],
        'prefix_evidence':'ONLY terminal Top10 paths, no intermediate beam scores/ancestry; first_missing_final_prefix_depth is not pruning step',
        'case_selection':'minimum qid lexicographically per predeclared partition and per method/baseline-only exposure stratum; no manual cherry-pick',
        'privacy':'per-user rows, exact exposure counts and linked paper cases stay in ignored data/stage46-audit',
        'forbidden':['training','generation','model load','dev analysis','new source acquisition','changing old files',
                     'significance or causal claim','training/candidate selection using future liked targets'],
        'files':{str(path):digest(path) for path in sorted(paths)}}
    assert digest(paths[0])==protocol['old_receipt_sha256']
    save(REPORT/'protocol.json',protocol)
    catalog={r['doc_id']:r for r in read(Path('data/stage44-supervision/catalog.json'))};ids=set(catalog)
    mappings={a:read(Path('data/stage45-sft')/(a+'.tokens.json')) for a in ['content','shuffled']}
    assert all(set(m)==ids for m in mappings.values())
    raw_counts=Counter(tuple(t[:3]) for t in mappings['content'].values())
    order=read(Path('data/stage45-sft/training-order.json'))
    selected_ids=order['sample_ids'][:1024];selected_set=set(selected_ids)
    pool_counts=Counter();pool_users=set();pilot_counts=Counter();history_counts=Counter();pilot_users=set();selected={}
    pool_events=0
    for row in json_rows(Path('data/stage44-supervision/train.next_item.jsonl')):
        pool_events+=1;pool_counts[row['target_doc_id']]+=1;pool_users.add(row['user_key'])
        if row['sample_id'] in selected_set:
            selected[row['sample_id']]=row;pilot_counts[row['target_doc_id']]+=1
            history_counts.update(row['history_doc_ids']);pilot_users.add(row['user_key'])
    assert len(selected)==1024 and pool_events==98887
    save(DATA/'selected-samples.json',[selected[s] for s in selected_ids])
    source=read(Path('data/stage44-supervision/training-stats.json'))['catalog_source_positive_counts']
    eligible=Counter(r['doc_id'] for r in json_rows(Path('data/stage44-supervision/train.feedback.jsonl'))
                     if r['rating']==1 and r['available_at_event'])
    profiles={r['user_key']:r for r in json_rows(Path('data/stage44-supervision/profiles.jsonl'))}
    labels=list(json_rows(Path('data/stage44-supervision/tuning.labels.jsonl')))
    assert len(labels)==46352
    contexts={u:p['eligible_train_positive_count']>0 for u,p in profiles.items()}
    partitions=Counter();strata=Counter();exposure_by_event=Counter();mapping_by_event=Counter();case_candidates={}
    label_meta={}
    for label in labels:
        qid=label['qid'];doc=label['target_doc_id'];user=label['user_key'];context=contexts.get(user,False)
        availability=availability_group(label,context)
        exposure=exposure_group(doc,source,eligible,pool_counts,pilot_counts,ids)
        mutation=mapping_group(doc,mappings['content'],mappings['shuffled'],raw_counts)
        partitions[availability]+=1;strata[(availability,exposure)]+=1
        exposure_by_event[exposure]+=1;mapping_by_event[mutation]+=1
        if doc in ids:
            assert label['target_version_key']==catalog[doc]['version_key']
        label_meta[qid]={'availability':availability,'exposure':exposure,'mapping':mutation,'has_context':context}
        key='partition:'+availability if availability!='rankable_with_context' else 'exposure:'+exposure
        if key not in case_candidates or qid<case_candidates[key]['qid']:
            case_candidates[key]=label|{'case_type':key}
    assert sum(partitions.values())==46352
    save(DATA/'item-exposure.json',{doc:{'source_train_likes':source.get(doc,0),'proxy_eligible_train_likes':eligible.get(doc,0),
        'full_pool_target_count':pool_counts.get(doc,0),'pilot_label_count':pilot_counts.get(doc,0),
        'pilot_history_count':history_counts.get(doc,0),
        'group':exposure_group(doc,source,eligible,pool_counts,pilot_counts,ids),
        'mapping_group':mapping_group(doc,mappings['content'],mappings['shuffled'],raw_counts)} for doc in sorted(ids)})
    coverage={'full_pool_samples':pool_events,'full_pool_users':len(pool_users),'full_pool_target_papers':len(pool_counts),
        'pilot_samples':1024,'pilot_users':len(pilot_users),'pilot_target_papers':len(pilot_counts),
        'pilot_history_papers':len(history_counts),'pilot_history_item_occurrences':sum(history_counts.values()),
        'target_not_labelled_but_in_history':len(set(history_counts)-set(pilot_counts)),
        'catalog_item_exposure_groups':dict(Counter(exposure_group(d,source,eligible,pool_counts,pilot_counts,ids) for d in ids)),
        'user_profiles':len(profiles),'source_training_profiles_with_context':sum(contexts.values()),
        'pilot_user_fraction_of_pool_users':len(pilot_users)/len(pool_users),
        'pilot_target_fraction_of_pool_targets':len(pilot_counts)/len(pool_counts),
        'prefix_coverage':{a:prefix_coverage(mapping,pilot_counts,history_counts,pool_counts) for a,mapping in mappings.items()},
        'same_selected_samples_and_token_budget_for_six_runs':True}
    baseline_users={method:predictions_by_user(Path('data/stage45-sft')/(method+'.tuning.predictions.jsonl'),labels)
                    for method in ['popular','content','sar']}
    results={};prefix_results={};comparisons={};group_rows=[];all_traces_verified=0;all_rows_verified=0;all_raw={}
    methods=[(m,None,None) for m in ['popular','content','sar']]
    methods += [(arm+'-'+str(seed),arm,seed) for seed in [42,2024,3407] for arm in ['content','shuffled']]
    for method,arm,seed in methods:
        if arm is None:
            users=baseline_users[method];raw=None
        else:
            run=Path('runs/stage45')/method
            users=predictions_by_user(run/'tuning.predictions.jsonl',labels)
            raw=read(run/'raw-user-decoding.json')
            all_raw[method]=raw
            assert set(raw)==set(users)
            for user,trace in raw.items():
                assert trace['doc_ids']==users[user]
                assert trace['fallback']==(not contexts.get(user,False))
                assert len(trace['doc_ids'])==10 and len(set(trace['doc_ids']))==10
                assert not set(trace['doc_ids']).intersection(profiles.get(user,{}).get('seen_doc_ids',[]))
                if not trace['fallback']:
                    assert trace['token_ids']==[mappings[arm][d] for d in trace['doc_ids']]
                    all_traces_verified+=1
        accumulator=MetricAccumulator();prefix_counts=Counter();lost=Counter();differences=Counter();miss_rows=[]
        for label in labels:
            qid=label['qid'];user=label['user_key'];doc=label['target_doc_id'];meta=label_meta[qid]
            availability=meta['availability'];exposure=meta['exposure'];mutation=meta['mapping']
            groups=['full',availability]
            if label['rankable']:
                groups += ['rankable_all','rankable_exposure:'+exposure]
            if availability=='rankable_with_context':
                groups += ['context_exposure:'+exposure,'context_mapping:'+mutation,
                           'context_user_pilot:'+('seen' if user in pilot_users else 'not_seen'),
                           'context_target_history:'+('seen' if history_counts.get(doc,0) else 'not_seen')]
            hit=accumulator.add(groups,user,users[user],doc);all_rows_verified+=1
            if raw is None or availability!='rankable_with_context':continue
            status=final_prefix_status(mappings[arm][doc],raw[user]['token_ids'],hit)
            prefix_counts['events']+=1;prefix_counts['hits']+=int(hit)
            for depth,covered in enumerate(status['prefix_covered'],1):
                prefix_counts['target_final_prefix_covered_depth_'+str(depth)]+=int(covered)
            if not hit:
                missing=status['first_missing_final_prefix_depth']
                prefix_counts['missing_at_depth_'+str(missing)]+=1
                lost[exposure]+=1
                miss_rows.append({'qid':qid,'user_key':user,'target_doc_id':doc,'exposure':exposure,
                    'mapping_group':mutation,**status})
            baseline_hit=doc in baseline_users['content'][user]
            diff=('both_hit' if baseline_hit and hit else 'content_only_hit' if baseline_hit else
                  'sid_only_hit' if hit else 'both_miss')
            differences[diff]+=1
            differences[diff+':'+exposure]+=1;differences[diff+':'+mutation]+=1
            if diff=='content_only_hit':
                key='content_only:'+method+':'+exposure+':'+mutation
                if key not in case_candidates or qid<case_candidates[key]['qid']:
                    case_candidates[key]=label|{'case_type':key,'method':method,'prefix_status':status}
        exported=accumulator.export();original=read(REPORT.parent/'stage45'/(method+'.tuning.score.json'))
        for key in ['user_macro','event_micro']:
            assert all(abs(exported['full'][key][k]-v)<1e-14 for k,v in original[key].items())
        assert exported['full']['events']==original['events'] and exported['full']['users']==original['users']
        results[method]=exported
        for group,values in exported.items():
            group_rows.append({'method':method,'group':group,'events':values['events'],'users':values['users'],
                'hit_events':values['hit_events'],**values['user_macro']})
        if raw is not None:
            assert sum(prefix_counts['missing_at_depth_'+str(d)] for d in [1,2,3,4])+prefix_counts['hits']==prefix_counts['events']
            prefix_results[method]={'counts':dict(prefix_counts),'miss_exposure_counts':dict(lost),
                'unit':'evaluation event within method; same frozen profile can recur',
                'interpretation':'first absent target prefix among final Top10, NOT actual beam pruning time'}
            comparisons[method]=dict(differences)
            with (DATA/(method+'.terminal-prefix-misses.jsonl')).open('x',encoding='utf-8',newline='\n') as stream:
                for row in miss_rows:stream.write(json.dumps(row,separators=(',',':'))+'\n')
        print({'audited':method,'full_events':exported['full']['events'],
               'rankable_context_events':exported.get('rankable_with_context',{}).get('events',0)},flush=True)
    cases=[]
    for index,(key,label) in enumerate(sorted(case_candidates.items()),1):
        doc=label['target_doc_id'];user=label['user_key'];meta=label_meta[label['qid']]
        method=label.get('method');arm=method.split('-')[0] if method else None
        trace=all_raw[method][user] if method else None
        case={'case_id':f'S46-{index:03d}','case_type':key,'qid':label['qid'],'user_key':user,
            'target_doc_id':doc,'target_metadata':{k:catalog[doc][k] for k in ['title','abstract','version_key','source_url']} if doc in catalog else None,
            **meta,'target_source_train_likes':source.get(doc,label['target_train_positive_count']),
            'target_eligible_train_likes':eligible.get(doc,0),
            'target_full_pool_samples':pool_counts.get(doc,0),'target_pilot_labels':pilot_counts.get(doc,0),
            'target_pilot_history_occurrences':history_counts.get(doc,0),
            'history':[{'doc_id':d,**{k:catalog[d][k] for k in ['title','version_key','source_url']}}
                       for d in profiles.get(user,{}).get('history_doc_ids',[])],
            'baseline_content_top10':baseline_users['content'][user],
            'baseline_target_rank':(baseline_users['content'][user].index(doc)+1) if doc in baseline_users['content'][user] else None,
            'sid_method':method,'sid_trace':trace,'target_sid':mappings[arm].get(doc) if arm else None,
            'prefix_status':label.get('prefix_status'),'selection_rule':'lexicographically minimum qid of this predefined stratum'}
        cases.append(case)
    save(DATA/'cases.json',cases)
    lines=['# 阶段46本地案例（逐用户衍生，仅本地研究）','',
           '按预先固定分组取字典序最小qid；不是人工挑选的相关性案例。论文原摘要仍取冻结明确v1元数据。目录外文本未知，不补写版本或摘要。','']
    for case in cases:
        metadata=case['target_metadata']
        lines += [f"## {case['case_id']} · {case['case_type']}",'',
            f"目标：{case['target_doc_id']}；画像上下文：{case['has_context']}；曝光分类：{case['exposure']}。",
            f"训练期源点赞/合规点赞/监督池目标/本轮标签：{case['target_source_train_likes']}/{case['target_eligible_train_likes']}/{case['target_full_pool_samples']}/{case['target_pilot_labels']}。"]
        if metadata:lines += [f"论文：[{metadata['title']}]({metadata['source_url']}) · {metadata['version_key']}",'',metadata['abstract']]
        else:lines += ['目录外，没有本快照可核验的标题/原摘要/明确版本。']
        if case['sid_method']:
            lines += ['',f"内容基线目标排名：{case['baseline_target_rank']}；SID运行：{case['sid_method']}。",
                      f"目标SID：`{case['target_sid']}`；终局前缀诊断：`{case['prefix_status']}`。",
                      f"最终SID Top10：`{case['sid_trace']['doc_ids']}`。"]
        lines+=['','历史（最后三篇，仅展示冻结真实上下文）：']
        lines += [f"- [{row['title']}]({row['source_url']}) · {row['version_key']}" for row in case['history'][-3:]]
        lines+=['']
    (DATA/'cases.md').write_text('\n'.join(lines),encoding='utf-8')
    write_csv(REPORT/'conditional-metrics.csv',group_rows)
    write_csv(REPORT/'availability-exposure-counts.csv',[{'availability':a,'exposure':e,'events':n} for (a,e),n in sorted(strata.items())])
    write_csv(REPORT/'terminal-prefix-counts.csv',[{'method':m,**{key:row['counts'].get(key,0) for key in
        ['events','hits','missing_at_depth_1','missing_at_depth_2','missing_at_depth_3','missing_at_depth_4']}}
        for m,row in prefix_results.items()])
    result={'protocol_sha256':digest(REPORT/'protocol.json'),'scope':protocol['scope'],
        'availability_partition':dict(partitions),'exposure_events_all':dict(exposure_by_event),
        'mapping_events_all':dict(mapping_by_event),'coverage':coverage,'metrics':results,
        'terminal_prefix':prefix_results,'baseline_content_vs_sid':comparisons,
        'case_index':[{'case_id':r['case_id'],'case_type':r['case_type']} for r in cases],
        'validation':{'all_9_full_scores_reproduced_to_1e_14':True,'prediction_event_rows_verified':all_rows_verified,
            'raw_neural_profile_traces_verified':all_traces_verified,'no_model_load_fit_generate':True,
            'no_intermediate_beam_ancestry_or_scores_available':True},
        'seconds':time.perf_counter()-start}
    save(REPORT/'audit.json',result)
    print({'audit':'complete','availability':dict(partitions),'coverage':{k:v for k,v in coverage.items() if k!='prefix_coverage'},
           'seconds':result['seconds']},flush=True)


if __name__=='__main__':main()
