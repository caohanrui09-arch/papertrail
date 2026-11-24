"""Stage49 source-frozen offline attribution of existing128/512 predictions."""
from collections import Counter,defaultdict
import csv
import json
from pathlib import Path
import subprocess
import sys
import time

from gsearch.quality_protocol import digest,save
from gsearch.sid_budget_audit import (ROOT,DATA,read,exposure,frequency_bin,rank_of,transition,
    weighted_change,select_case,output_summary,concentration,TRANSITIONS)
from gsearch.sid_failure_audit import MetricAccumulator,availability_group,final_prefix_status,prefix_coverage
from gsearch.supervision import json_rows
from scripts.audit_sid_failures import predictions_by_user


def write_csv(path: Path,rows: list[dict]) -> None:
    with path.open('x',encoding='utf-8-sig',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def add_bucket(buckets: dict,groups: list[str],user: str,kind: str,delta: dict) -> None:
    for key in groups:
        b=buckets[key];b['events']+=1;b['users'].add(user);b['transitions'][kind]+=1
        b['weighted_ndcg_delta']+=delta['ndcg'];b['weighted_recall_delta']+=delta['recall']
        b['gross_positive_ndcg']+=max(0,delta['ndcg']);b['gross_negative_ndcg']-=min(0,delta['ndcg'])


def main() -> None:
    if ROOT.exists() or DATA.exists():raise FileExistsError('Preserve any prior stage49 attempt')
    subprocess.run([sys.executable,'-E','-s','-m','scripts.verify_sid_budget'],check=True)
    ROOT.mkdir(parents=True);DATA.mkdir(parents=True)
    files=[Path('reports/stage48/final-validation.json'),Path('data/stage46-audit/item-exposure.json'),
        Path('data/stage45-sft/training-order.json'),Path('data/stage48-budget/order.json'),
        Path('data/stage44-supervision/train.next_item.jsonl'),Path('data/stage44-supervision/catalog.json'),
        Path('data/stage44-supervision/profiles.jsonl'),Path('data/stage44-supervision/tuning.labels.jsonl'),
        Path('data/stage45-sft/content.tuning.predictions.jsonl'),Path('gsearch/sid_budget_audit.py'),
        Path('gsearch/sid_failure_audit.py'),Path('gsearch/evaluate.py'),Path('gsearch/supervision.py'),
        Path('scripts/audit_sid_failures.py'),Path('scripts/audit_sid_budget_changes.py'),
        Path('scripts/validate_sid_budget_changes.py'),Path('tests/test_sid_budget_audit.py')]
    for arm in ['content','shuffled']:files.append(Path('data/stage45-sft')/(arm+'.tokens.json'))
    runs=[a+'-'+str(s) for s in [42,2024,3407] for a in ['content','shuffled']]
    for run in runs:
        for stage,report in [('stage45','stage45'),('stage48','stage48')]:
            files.extend(Path('runs')/stage/run/name for name in ['tuning.predictions.jsonl','raw-user-decoding.json'])
            files.append(Path('reports')/report/(run+'.tuning.score.json'))
    protocol={'frozen_before_stage49_audit':True,'scope':'posthoc descriptive reused-tuning audit, no causal or fresh-test claim',
        'prior_receipt_sha256':'7de4e3e0b259fbac26288b547304a060c3de8b9cbb221e6584190117532f144c',
        'target_exposure':'paper ever labelled in first1024 / first labelled in1025..4096 / pool target still unselected; remaining source/proxy groups separate; history exposure not label exposure',
        'transitions':TRANSITIONS,'delta':'native metrics; each event weight1/(3571*full_events_of_user); cohort deltas add to full delta, conditional macro not additive',
        'frequency':'source-train likes bins0/1..4/5..19/20+ fixed for both budgets; label probability normalizes1024/4096 separately',
        'concentration':'unique context profiles only; top-user/paper share uses gross positive event NDCG credit, never net delta',
        'case_selection':'minimum qid per run x transition(new/lost/retained-up/down) x target exposure among1801 context-rankable events',
        'terminal_prefix':'only final Top10 paths, no intermediate pruning or score/displacement causality',
        'recommendation_heuristic':'consider fixed1024-repeat4 vs4096-single-pass at512 if newly-labelled targets exceed50% gross positive NDCG in>=2of3 content seeds; heuristic, not causal evidence or statistical test',
        'forbidden':['training','generation','model load','dev evaluation','new dependencies','old file edits','website changes','RL'],
        'privacy':'linked user/paper cases, exposure map and per-event rows remain ignored local data',
        'files':{str(p):digest(p) for p in sorted(set(files))}}
    assert digest(files[0])==protocol['prior_receipt_sha256']
    save(ROOT/'protocol.json',protocol)
    started=time.perf_counter()
    order=read(Path('data/stage45-sft/training-order.json'));ids1024=set(order['sample_ids'][:1024]);ids4096=set(order['sample_ids'][:4096])
    assert read(Path('data/stage48-budget/order.json'))['sample_ids']==order['sample_ids'][:4096]
    targets={128:Counter(),512:Counter()};histories={128:Counter(),512:Counter()};users={128:set(),512:set()}
    for row in json_rows(Path('data/stage44-supervision/train.next_item.jsonl')):
        for budget,selected in [(128,ids1024),(512,ids4096)]:
            if row['sample_id'] in selected:
                targets[budget][row['target_doc_id']]+=1;histories[budget].update(row['history_doc_ids']);users[budget].add(row['user_key'])
    assert sum(targets[128].values())==1024 and sum(targets[512].values())==4096
    items=read(Path('data/stage46-audit/item-exposure.json'))
    item_map={d:row|{'expanded_label_count':targets[512][d],'expanded_history_count':histories[512][d],
        'budget_exposure':exposure(d,items,targets[512])} for d,row in items.items()}
    save(DATA/'item-exposure.json',item_map)
    catalog={r['doc_id']:r for r in read(Path('data/stage44-supervision/catalog.json'))}
    profiles={r['user_key']:r for r in json_rows(Path('data/stage44-supervision/profiles.jsonl'))}
    labels=list(json_rows(Path('data/stage44-supervision/tuning.labels.jsonl')));user_events=Counter(r['user_key'] for r in labels)
    assert len(labels)==46352 and len(user_events)==3571
    mappings={a:read(Path('data/stage45-sft')/(a+'.tokens.json')) for a in ['content','shuffled']}
    baseline=predictions_by_user(Path('data/stage45-sft/content.tuning.predictions.jsonl'),labels)
    meta={};partitions=Counter();cohort_events=Counter();conditional_events=Counter()
    for r in labels:
        available=availability_group(r,profiles.get(r['user_key'],{}).get('eligible_train_positive_count',0)>0)
        cohort=exposure(r['target_doc_id'],items,targets[512]);meta[r['qid']]={'availability':available,'exposure':cohort}
        partitions[available]+=1;cohort_events[cohort]+=1
        if available=='rankable_with_context':conditional_events[cohort]+=1
    assert partitions['rankable_with_context']==1801
    coverage={'catalog_groups':dict(Counter(r['budget_exposure'] for r in item_map.values())),
        'newly_labelled_papers':len(set(targets[512])-set(targets[128])),
        'newly_labelled_papers_already_in1024_history':len((set(targets[512])-set(targets[128]))&set(histories[128])),
        'evaluation_target_groups':dict(cohort_events),'conditional_target_groups':dict(conditional_events),
        'supervision':{str(b):{'samples':sum(targets[b].values()),'target_papers':len(targets[b]),'users':len(users[b]),
            'history_papers':len(histories[b]),'history_only_not_label':len(set(histories[b])-set(targets[b]))} for b in [128,512]},
        'prefix':{arm:{str(b):prefix_coverage(mapping,targets[b],histories[b],
            {d:r['full_pool_target_count'] for d,r in items.items()}) for b in [128,512]} for arm,mapping in mappings.items()}}
    results={};case_candidates={};gain_rows=[];output_rows=[];prefix_rows=[];frequency_rows=[]
    for run in runs:
        arm=run.split('-')[0];mapping=mappings[arm]
        predictions={};raw={};acc={128:MetricAccumulator(),512:MetricAccumulator()}
        for b,stage in [(128,'stage45'),(512,'stage48')]:
            directory=Path('runs')/stage/run
            predictions[b]=predictions_by_user(directory/'tuning.predictions.jsonl',labels)
            raw[b]=read(directory/'raw-user-decoding.json')
            for u,row in raw[b].items():
                assert row['doc_ids']==predictions[b][u] and len(row['doc_ids'])==len(set(row['doc_ids']))==10
                assert not set(row['doc_ids']).intersection(profiles.get(u,{}).get('seen_doc_ids',[]))
                if not row['fallback']:assert row['token_ids']==[mapping[d] for d in row['doc_ids']]
        buckets=defaultdict(lambda:{'events':0,'users':set(),'transitions':Counter(),'weighted_ndcg_delta':0.,
            'weighted_recall_delta':0.,'gross_positive_ndcg':0.,'gross_negative_ndcg':0.})
        changes=[];prefix_records=[];prefix_stats={128:Counter(),512:Counter()};lost_frequency=Counter()
        for label in labels:
            qid=label['qid'];u=label['user_key'];doc=label['target_doc_id'];info=meta[qid]
            cohort=info['exposure'];availability=info['availability'];is_context=availability=='rankable_with_context'
            old=predictions[128][u];new=predictions[512][u]
            ranks={128:rank_of(old,doc),512:rank_of(new,doc)};kind=transition(ranks[128],ranks[512])
            delta=weighted_change(u,old,new,doc,user_events)
            groups=['full',availability,'exposure:'+cohort]
            if is_context:groups+=['context_exposure:'+cohort]
            add_bucket(buckets,groups,u,kind,delta)
            for b in [128,512]:acc[b].add(groups,u,predictions[b][u],doc)
            record={'qid':qid,'user_key':u,'target_doc_id':doc,**info,'transition':kind,
                'old_rank':ranks[128],'new_rank':ranks[512],'weighted_delta':delta,
                'baseline_content_rank':rank_of(baseline[u],doc)}
            if kind not in ['both_miss','retained_same']:
                assert is_context, 'Shared zero-context fallback cannot change'
                added=[d for d in new if d not in old]
                record.update({'target_source_likes':items[doc]['source_train_likes'],
                    'target_old_labels':targets[128][doc],'target_new_labels':targets[512][doc],
                    'target_first1024_history_count':histories[128][doc],
                    'added_papers':added,'added_source_likes':[items[d]['source_train_likes'] for d in added],
                    'added_new_label_counts':[targets[512][d] for d in added]})
                changes.append(record)
                select_case(case_candidates,run+':'+kind+':'+cohort,record|{'run':run})
                if kind=='lost_hit':
                    lost_frequency['lost_hit_events']+=1
                    lost_frequency['with_any_added_higher_source_frequency']+=int(any(items[d]['source_train_likes']>items[doc]['source_train_likes'] for d in added))
                    lost_frequency['with_any_added_higher_expanded_label_frequency']+=int(any(targets[512][d]>targets[512][doc] for d in added))
            if is_context:
                status={}
                for b in [128,512]:
                    status[b]=final_prefix_status(mapping[doc],raw[b][u]['token_ids'],ranks[b] is not None)
                    prefix_stats[b]['events']+=1
                    prefix_stats[b]['hits']+=int(ranks[b] is not None)
                    for depth,covered in enumerate(status[b]['prefix_covered'],1):prefix_stats[b]['covered_'+str(depth)]+=int(covered)
                    if ranks[b] is None:prefix_stats[b]['missing_'+str(status[b]['first_missing_final_prefix_depth'])]+=1
                prefix_records.append({**record,'old_prefix':status[128],'new_prefix':status[512]})
        metrics_by_budget={str(b):acc[b].export() for b in [128,512]}
        for b,stage in [(128,'stage45'),(512,'stage48')]:
            reference=read(Path('reports')/stage/(run+'.tuning.score.json'))
            for group in ['user_macro','event_micro']:
                assert all(abs(metrics_by_budget[str(b)]['full'][group][k]-v)<1e-14 for k,v in reference[group].items())
        frozen_buckets={k:{**v,'users':len(v['users']),'transitions':{kind:v['transitions'][kind] for kind in TRANSITIONS}}
                        for k,v in buckets.items()}
        expected=metrics_by_budget['512']['full']['user_macro']['ndcg@10']-metrics_by_budget['128']['full']['user_macro']['ndcg@10']
        assert abs(frozen_buckets['full']['weighted_ndcg_delta']-expected)<1e-14
        assert abs(sum(v['weighted_ndcg_delta'] for k,v in frozen_buckets.items() if k.startswith('exposure:'))-expected)<1e-14
        outputs={str(b):output_summary(raw[b],mapping,items,targets[b]) for b in [128,512]}
        # Unique context-profile additions/removals use the same immutable frequency scale.
        moved={'added':Counter(),'removed':Counter()}
        for u in raw[128]:
            assert raw[128][u]['fallback']==raw[512][u]['fallback']
            if raw[128][u]['fallback']:continue
            oldset=set(predictions[128][u]);newset=set(predictions[512][u])
            moved['added'].update(newset-oldset);moved['removed'].update(oldset-newset)
        movement={kind:{'slots':sum(c.values()),'unique_papers':len(c),
            'source_likes_mean':sum(items[d]['source_train_likes']*n for d,n in c.items())/sum(c.values()) if c else None,
            'expanded_label_mean':sum(targets[512][d]*n for d,n in c.items())/sum(c.values()) if c else None} for kind,c in moved.items()}
        for b in [128,512]:
            o=outputs[str(b)]
            output_rows.append({'run':run,'budget':b,**{k:o[k] for k in ['context_users','slots','unique_papers','catalog_coverage','top1_max_share','source_likes_slot_mean','label_probability_slot_mean']}})
            prefix_rows.append({'run':run,'budget':b,**{k:prefix_stats[b][k] for k in ['events','hits','missing_1','missing_2','missing_3','missing_4']}})
            for bin_name,n in o['source_frequency_slots'].items():frequency_rows.append({'run':run,'budget':b,'source_frequency_bin':bin_name,'slots':n,'share':n/o['slots']})
        for key,v in frozen_buckets.items():
            gain_rows.append({'run':run,'group':key,'events':v['events'],'users':v['users'],**v['transitions'],
                **{k:v[k] for k in ['weighted_ndcg_delta','weighted_recall_delta','gross_positive_ndcg','gross_negative_ndcg']}})
        for filename,rows in [(run+'.changes.jsonl',changes),(run+'.terminal-prefix.jsonl',prefix_records)]:
            with (DATA/filename).open('x',encoding='utf-8',newline='\n') as handle:
                for row in rows:handle.write(json.dumps(row,separators=(',',':'))+'\n')
        results[run]={'metrics':metrics_by_budget,'changes':frozen_buckets,'concentration':concentration(changes),
            'output':outputs,'terminal_prefix':{str(k):dict(v) for k,v in prefix_stats.items()},
            'profile_movement':movement,'lost_hit_frequency_cooccurrence':dict(lost_frequency),
            'changed_event_rows':len(changes),'new_hits_also_hit_by_content_baseline':sum(r['transition']=='new_hit' and r['baseline_content_rank'] is not None for r in changes)}
        print({'audited':run,'transitions':frozen_buckets['full']['transitions'],'delta':expected},flush=True)
    cases=[]
    for index,(key,row) in enumerate(sorted(case_candidates.items()),1):
        run=row['run'];arm=run.split('-')[0];doc=row['target_doc_id'];u=row['user_key']
        traces={str(b):read(Path('runs')/stage/run/'raw-user-decoding.json')[u] for b,stage in [(128,'stage45'),(512,'stage48')]}
        cases.append({'case_id':f'S49-{index:03d}','case_type':key,**row,
            'target_metadata':{k:catalog[doc][k] for k in ['title','abstract','version_key','source_url']},
            'target_sid':mappings[arm][doc],'traces':traces,
            'history':[{'doc_id':d,**{k:catalog[d][k] for k in ['title','version_key','source_url']}} for d in profiles[u]['history_doc_ids'][-3:]],
            'selection':'minimum qid per predeclared run/transition/exposure stratum'})
    save(DATA/'cases.json',cases)
    lines=['# 阶段49本地案例','', '逐用户衍生，仅本地研究。按固定分组最小qid取例，不是人工相关性判断。','']
    for row in cases:
        m=row['target_metadata']
        lines += [f"## {row['case_id']} · {row['case_type']}",'',f"论文：[{m['title']}]({m['source_url']}) · {row['target_doc_id']} · {m['version_key']}",'',m['abstract'],'',
            f"目标排名128→512：{row['old_rank']}→{row['new_rank']}；原内容基线排名：{row['baseline_content_rank']}。",
            f"目标源训练赞/1024标签/4096标签：{row['target_source_likes']}/{row['target_old_labels']}/{row['target_new_labels']}；目标SID：{row['target_sid']}。",
            f"完整分母加权NDCG贡献：{row['weighted_delta']['ndcg']:+.12f}。",
            f"新增候选：{row['added_papers']}；对应源频率：{row['added_source_likes']}；对应4096标签频率：{row['added_new_label_counts']}。",
            f"128 Top10：{row['traces']['128']['doc_ids']}。",f"512 Top10：{row['traces']['512']['doc_ids']}。",'', '最近三篇历史：']
        lines += [f"- [{h['title']}]({h['source_url']}) · {h['version_key']}" for h in row['history']]
        lines += ['','频率共现不是挤压的因果证明；终局路径不能恢复中间beam剪枝。','']
    (DATA/'cases.md').write_text('\n'.join(lines),encoding='utf-8')
    write_csv(ROOT/'gain-attribution.csv',gain_rows);write_csv(ROOT/'output-coverage.csv',output_rows)
    write_csv(ROOT/'terminal-prefix.csv',prefix_rows);write_csv(ROOT/'source-frequency-slots.csv',frequency_rows)
    save(ROOT/'audit.json',{'protocol_sha256':digest(ROOT/'protocol.json'),'availability':dict(partitions),'coverage':coverage,
        'runs':results,'cases':[{'case_id':c['case_id'],'case_type':c['case_type']} for c in cases],
        'full_denominator':46352,'full_users':3571,'conditional_diagnostic_events':1801,
        'reproduced_full_scores':12,'paired_event_comparisons':6*46352,'terminal_prefix_checks':12*1801,
        'seconds':time.perf_counter()-started,'no_model_load_fit_generate':True,'dev_evaluated':False,'rl_started':False})
    assert 'torch' not in sys.modules and 'transformers' not in sys.modules
    print({'audit':'complete','cases':len(cases),'seconds':time.perf_counter()-started},flush=True)


if __name__=='__main__':main()
