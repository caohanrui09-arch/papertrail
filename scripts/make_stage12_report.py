"""Validate source joins/sample provenance and publish aggregate-only cost/coverage audit."""
from collections import Counter,defaultdict
from pathlib import Path
import json
import re

import pandas as pd

from gsearch.catalog_audit import CACHE,DATA,REPORT,SOURCE,SAMPLE_GROUPS,SAMPLE_N,arrow,digest,read,reason,sample_key,sample_stratum,stamp
from scripts.audit_catalog_coverage import ORIGINAL,STRATA,save

LABELS={
 'inside_current_catalog':'现目录内',
 'old_trainliked_topk_truncated':'截止前旧论文有训练点赞，被Top-K截断',
 'old_trainliked_version_excluded':'原2048内旧论文因文本日期筛选被排除',
 'old_without_training_likes':'截止前已提交，无训练点赞',
 'published_after_train_cutoff':'源首次版本日在训练截止后',
 'unknown_metadata_or_first_date':'缺源记录或首次版本日期',
 'source_first_date_after_feedback':'源首次版本日晚于点赞，时间异常'
}

def verify_history() -> None:
    from scripts.make_stage8_report import verify_history as check3_7
    from gsearch.benchmark_target_alignment import check_plan as check8
    from gsearch.benchmark_recommendation import check_plan as check9
    check3_7(); check8(); check9()
    for stage in (8,9,11):
        base=Path(f'reports/stage{stage}')
        old=read(base/'final-validation.json')
        if any(digest(base/n)!=v for n,v in old['outputs'].items()):
            raise ValueError('Historical report assets changed')
        if any(digest(Path(n))!=v for n,v in old.get('code_assets',{}).items()):
            raise ValueError('Historical source assets changed')
    old=read(Path('reports/stage10/final-validation.json'))
    for base,key in ((Path('data/stage10-catalog'),'data_assets'),(Path('.'),'code_assets')):
        if any(digest(base/n)!=v for n,v in old[key].items()):
            raise ValueError('Stage10 assets changed')

def main() -> None:
    plan=read(REPORT/'plan.json')
    coverage=read(REPORT/'coverage-aggregate.json')
    if coverage['plan_sha256']!=digest(REPORT/'plan.json') or plan['source_sha256']!=digest(SOURCE):
        raise ValueError('Audit plan/source drift')
    if any(digest(Path(n))!=v for n,v in plan['source_code'].items()):
        raise ValueError('Frozen acquisition/classification source changed')
    if any(digest(ORIGINAL/(s+'.csv'))!=v for s,v in plan['feedback'].items()):
        raise ValueError('Feedback drift')
    arrow()
    import pyarrow.parquet as pq
    import pyarrow as pa
    import pyarrow.compute as pc
    train=pd.read_csv(ORIGINAL/'train.csv',dtype={'arxiv_id':str,'user_id':str})
    trainlikes=set(train.loc[train.rating==1,'arxiv_id'])
    catalog=set(read(Path('data/stage11-content/catalog.json')))
    oldcatalog=set(read(ORIGINAL/'catalog.json'))
    cutoff,end=stamp(plan['cutoff']),stamp(plan['log_end'])
    all_dates=read(DATA/'feedback-paper-dates.json')
    metadata={r['paper_id']:r for r in all_dates}
    if len(metadata)!=len(all_dates):
        raise ValueError('Duplicate joined metadata')
    sample=read(DATA/'sample-plan.json')
    if sample['future_labels_used'] or coverage['sample_plan_sha256']!=digest(DATA/'sample-plan.json'):
        raise ValueError('Sample selection drift')
    receipts={}
    sample_rows={}
    layout=read(CACHE/'layout.json')
    # Reproduce fixed samples; cost scenarios use train-only counts and source dates.
    eligible={d for d in trainlikes if d in metadata and stamp(metadata[d]['first_version_date']) is not None
              and stamp(metadata[d]['latest_version_date']) is not None
              and stamp(metadata[d]['first_version_date'])<=stamp(metadata[d]['latest_version_date'])<cutoff}
    counts=train[train.rating==1].arxiv_id.value_counts().to_dict()
    ordered=sorted(eligible,key=lambda d:(-counts[d],d))
    scenarios={f'top{n}':set(ordered[:n]) for n in (10000,20000)}
    scenarios['all_date_eligible_trainliked']=eligible
    scenario_groups=defaultdict(set)
    pool={s:[] for s in STRATA}
    expansion_check=Counter()
    train_like_array=pa.array(sorted(trainlikes))
    source_rows=0
    for g in layout['groups']:
        i=g['index']
        path=CACHE/'light'/f'group-{i:05d}.parquet'
        if coverage['source_parts_sha256'][path.name]!=digest(path):
            raise ValueError('Light source parts changed')
        table=pq.read_table(path)
        first=pc.cast(table['first_version_date'],pa.timestamp('us',tz='UTC'))
        latest=pc.cast(table['latest_version_date'],pa.timestamp('us',tz='UTC'))
        old=pc.less(first,pa.scalar(cutoff))
        old_text=pc.and_kleene(old,pc.and_kleene(pc.greater_equal(latest,first),pc.less(latest,pa.scalar(cutoff))))
        liked=pc.is_in(table['paper_id'],value_set=train_like_array)
        masks={'train_cutoff_first_date_only':old,'train_cutoff_latest_text_date_proxy':old_text,
            'old_trainliked_latest_pre_cutoff':pc.and_kleene(old_text,liked),
            'old_no_trainlike_latest_pre_cutoff':pc.and_kleene(old_text,pc.invert(liked)),
            'new_during_logged_window':pc.and_kleene(pc.greater_equal(first,pa.scalar(cutoff)),pc.less_equal(first,pa.scalar(end)))}
        for name,mask in masks.items():
            expansion_check[name]+=pc.sum(mask).as_py() or 0
        records=table.to_pylist()
        source_rows+=len(records)
        present={r['paper_id'] for r in records}
        for name,ids in scenarios.items():
            if present&ids:
                scenario_groups[name].add(i)
        if i in SAMPLE_GROUPS:
            for r in records:
                s=sample_stratum(r,cutoff,end,trainlikes)
                if s:
                    row={**r,'row_group':i,'stratum':s,'selection_sha256':sample_key(r['paper_id'])}
                    pool[s].append(row)
                    pool[s].sort(key=lambda x:x['selection_sha256'])
                    del pool[s][SAMPLE_N:]
    if source_rows!=coverage['source_rows']:
        raise ValueError('Light source row count mismatch')
    if any(coverage['expansion_date_counts'][name]!=n for name,n in expansion_check.items()):
        raise ValueError('Independent Arrow vectorized expansion counts differ')
    actual_samples=[r for s in STRATA for r in pool[s]]
    normalized=json.loads(json.dumps(actual_samples,default=lambda x:x.isoformat()))
    if normalized!=sample['samples']:
        raise ValueError('Source-only fixed sample did not reproduce')
    for i in SAMPLE_GROUPS:
        path=CACHE/'sample'/f'group-{i:05d}.parquet'
        receipt=read(path.with_suffix('.json'))
        if digest(path)!=receipt['sha256']:
            raise ValueError('Text sample part changed')
        receipts[i]=receipt
        for r in pq.read_table(path).to_pylist():
            if r['paper_id'] in sample_rows:
                raise ValueError('Duplicate sample record')
            sample_rows[r['paper_id']]=r
    if set(sample_rows)!={r['paper_id'] for r in sample['samples']}:
        raise ValueError('Text sample IDs differ')
    from gsearch.paper_identity import canonical_id
    sample_stats={}
    for s in STRATA:
        rows=[sample_rows[r['paper_id']] for r in sample['samples'] if r['stratum']==s]
        for r in rows:
            light=next(x for x in sample['samples'] if x['paper_id']==r['paper_id'])
            for k in ('paper_id','first_version_date','latest_version_date','n_versions'):
                actual=r[k].isoformat() if hasattr(r[k],'isoformat') else r[k]
                if actual!=light[k]:
                    raise ValueError('Text and light source rows differ')
            if canonical_id(r['arxiv_abs_url'])!=r['paper_id']:
                raise ValueError('Sample landing URL identity mismatch')
        sample_stats[s]={'rows':len(rows),'has_title':sum(bool((r['title'] or '').strip()) for r in rows),
            'has_abstract':sum(bool((r['abstract'] or '').strip()) for r in rows),
            'has_dates':sum(stamp(r['first_version_date']) is not None and stamp(r['latest_version_date']) is not None for r in rows),
            'has_reported_version_count':sum(isinstance(r['n_versions'],int) and r['n_versions']>=1 for r in rows),
            'title_abstract_utf8_bytes':sum(len(((r['title'] or '')+(r['abstract'] or '')).encode()) for r in rows)}
    # Independently recompute every diagnostic event and the cold-start split.
    validation={}
    like_users=set(train.loc[train.rating==1,'user_id'])
    catalog_users=set(train.loc[(train.rating==1)&train.arxiv_id.isin(catalog),'user_id'])
    all_users=set(train.user_id)
    all_items=set(train.arxiv_id)
    anomalies={}
    for split in ('tuning','dev'):
        frame=pd.read_csv(ORIGINAL/(split+'.csv'),dtype={'arxiv_id':str,'user_id':str})
        frame=frame[frame.rating==1]
        rows=read(DATA/(split+'-attribution.json'))
        if [(r['user_id'],r['arxiv_id'],r['time']) for r in rows]!=list(frame[['user_id','arxiv_id','time']].itertuples(index=False,name=None)):
            raise ValueError('Diagnostic events omitted/reordered')
        cause_counts=Counter()
        cross=Counter()
        flags=Counter()
        delta=[]
        for r in rows:
            d,u=r['arxiv_id'],r['user_id']
            m=metadata.get(d)
            why=reason(d,m,stamp(r['time']),cutoff,trainlikes,catalog,oldcatalog)
            if r['reason']!=why or r['cold_user_current_catalog']!=(u not in catalog_users) or r['cold_item_no_trainlike']!=(d not in trainlikes):
                raise ValueError('Attribution or user/item cold flag mismatch')
            first=stamp(m['first_version_date']) if m else None
            latest=stamp(m['latest_version_date']) if m else None
            expected_flag=('latest_date_unknown' if latest is None else 'snapshot_latest_after_feedback' if latest>stamp(r['time']) else 'snapshot_latest_not_after_feedback_proxy_only')
            if (r['text_time_flag']!=expected_flag or stamp(r['source_first_version_date'])!=first or
                    stamp(r['source_latest_version_date'])!=latest or r['cold_item_no_train_feedback']!=(d not in all_items) or
                    r['cold_user_global_likes']!=(u not in like_users)):
                raise ValueError('Source time or auxiliary cold flags differ')
            cause_counts[why]+=1
            cross[('cold_user' if u not in catalog_users else 'warm_user')+'__'+('cold_item' if d not in trainlikes else 'warm_item')]+=1
            flags[r['text_time_flag']]+=1
            if why=='source_first_date_after_feedback':
                delta.append((stamp(r['source_first_version_date'])-stamp(r['time'])).total_seconds()/3600)
        s=coverage['splits'][split]
        # Second attribution implementation uses vectorized pandas masks rather than reason().
        first=pd.to_datetime(frame.arxiv_id.map(lambda d:metadata.get(d,{}).get('first_version_date')),format='mixed',utc=True)
        event=pd.to_datetime(frame.time,format='mixed',utc=True)
        independent=pd.Series('old_without_training_likes',index=frame.index)
        independent.loc[frame.arxiv_id.isin(trainlikes)]='old_trainliked_topk_truncated'
        independent.loc[frame.arxiv_id.isin(trainlikes)&frame.arxiv_id.isin(oldcatalog)]='old_trainliked_version_excluded'
        independent.loc[frame.arxiv_id.isin(catalog)]='inside_current_catalog'
        independent.loc[first>=cutoff]='published_after_train_cutoff'
        independent.loc[first>event]='source_first_date_after_feedback'
        independent.loc[first.isna()]='unknown_metadata_or_first_date'
        if Counter(independent.tolist())!=cause_counts:
            raise ValueError('Independent vectorized attribution differs')
        if dict(cause_counts)!={k:v['like_events'] for k,v in s['causes'].items()} or dict(cross)!=s['event_cross_user_item_cold'] or dict(flags)!=s['snapshot_text_time_flags']:
            raise ValueError('Aggregate attribution mismatch')
        users=set(frame.user_id)
        if s['users']!={'cold_no_current_catalog_like':len(users-catalog_users),'warm_current_catalog_like':len(users&catalog_users),
             'cold_no_global_train_like':len(users-like_users),'no_train_feedback':len(users-all_users)}:
            raise ValueError('Cold user aggregate mismatch')
        if s['items']!={'cold_like_events_no_trainlike':int((~frame.arxiv_id.isin(trainlikes)).sum()),
             'cold_like_events_no_train_feedback':int((~frame.arxiv_id.isin(all_items)).sum()),'cold_unique_no_trainlike':len(set(frame.arxiv_id)-trainlikes)}:
            raise ValueError('Cold item aggregate mismatch')
        anomalies[split]={'events':len(delta),'within_24h':sum(x<=24 for x in delta),'over_24h':sum(x>24 for x in delta),'max_hours':max(delta) if delta else None}
        validation[split]=len(rows)
    train_anomalies=Counter()
    for r in train.itertuples(index=False):
        m=metadata.get(r.arxiv_id)
        first=stamp(m['first_version_date']) if m else None
        if first is not None and first>stamp(r.time):
            train_anomalies['positive_events' if r.rating==1 else 'negative_events']+=1
    api=read(DATA/'official-version-probe.json')
    official={'attempted':api['attempted'],'requested':len(api.get('requested_ids',[])),
              'returned':len(api.get('records',[])),'error':api.get('error'),'statuses':[r['status'] for r in api.get('requests',[])],
              'seconds':api.get('seconds'),'exact_version1':0,'first_date_matches_snapshot':0,
              'snapshot_text_exact_same_as_v1':0,'snapshot_text_whitespace_same_as_v1':0}
    for r in api.get('records',[]):
        base=sample_rows[r['doc_id']]
        if r['version']!=1 or not r['title'] or not r['abstract']:
            raise ValueError('Official v1 metadata incomplete')
        official['exact_version1']+=1
        official['first_date_matches_snapshot']+=stamp(r['published_at'])==stamp(base['first_version_date'])
        official['snapshot_text_exact_same_as_v1']+=r['title']==base['title'] and r['abstract']==base['abstract']
        official['snapshot_text_whitespace_same_as_v1']+=' '.join(r['title'].split())==' '.join(base['title'].split()) and ' '.join(r['abstract'].split())==' '.join(base['abstract'].split())
        for k in ('raw_path','raw_sha256'):
            if k not in r['provenance']:
                raise ValueError('Official source provenance missing')
        if digest(Path(r['provenance']['raw_path']))!=r['provenance']['raw_sha256']:
            raise ValueError('Official raw response hash mismatch')
    # Exact compressed column-block lower bounds, not row-count proportional extrapolation.
    scenario_costs={}
    for name,ids in scenarios.items():
        groups=scenario_groups[name]
        payload=sum(sum(g['compressed_bytes'][c] for c in ('paper_id','title','abstract')) for g in layout['groups'] if g['index'] in groups)
        scenario_costs[name]={'items':len(ids),'source_row_groups':len(groups),'compressed_id_title_abstract_blocks_bytes':payload,
             'dense_float64_sar_similarity_gib_lower_bound':8*len(ids)**2/2**30,
             'note':'Date eligible only, titles/abstracts not fully checked; counts/selection use train only; SAR bound excludes fit temporaries'}
        save(DATA/(name+'-cost-scenario.json'),{'paper_ids':sorted(ids),'selection':'train frequency descending, ID tie-break, source first<=latest<train cutoff; future labels unused'})
    runs={phase:[read(p) for p in sorted(CACHE.glob(phase+'-run-*.json'))] for phase in ('light','sample')}
    costs={phase:{'recorded_invocations':len(rs),'invocation_wall_seconds':sum(r['wall_seconds_this_invocation'] for r in rs),
                  'arrow_returned_bytes':sum(r['new_arrow_returned_bytes'] for r in rs),
                  'file_read_calls':sum(r['new_file_read_calls'] for r in rs),'complete':any(r['complete'] for r in rs)} for phase,rs in runs.items()}
    if not all(x['complete'] for x in costs.values()):
        raise ValueError('Acquisition incomplete')
    sample_rate=costs['sample']['arrow_returned_bytes']/costs['sample']['invocation_wall_seconds']
    for value in scenario_costs.values():
        value['rough_minutes_at_observed_sample_file_rate']=value['compressed_id_title_abstract_blocks_bytes']/sample_rate/60
    cost_detail={'observed':costs,'sample_stats':sample_stats,'official_version_probe':official,'source_block_cost_scenarios':scenario_costs,
        'source_all_id_title_abstract_compressed_bytes':sum(sum(g['compressed_bytes'][c] for c in ('paper_id','title','abstract')) for g in layout['groups']),
        'sample_log_ssl_retry_observed':'SSLError' in (REPORT/'sample-run.log').read_text(encoding='utf-8-sig'),
        'anomalies':anomalies,'train_first_date_after_feedback_events':dict(train_anomalies),
        'byte_note':'Arrow file.read returned bytes, excluding HTTP/TLS/API metadata, retries that failed before returning and process startup; not total wire traffic',
        'inference_latency':'No expanded recommender trained or latency measured; source acquisition cost only'}
    save(REPORT/'cost-and-sample-aggregate.json',cost_detail)
    future_protocol={'status':'design_only_no_new_ranking_runs','test_source':read(REPORT/'new-period-source-check.json'),
       'selection':'candidate IDs/text availability/size chosen from train and source dates only, no future-liked membership; bounded train-popularity cost scenarios not quality-tuned',
       'as_of':'fixed daily UTC bins for retrospective bookkeeping; every method shares exact source/version eligibility at each request. Use historical version/announcement evidence where acquired; latest snapshot proxy kept separate; first-observed ingestion for prospective runs',
       'history':'same original train feedback cutoff and all known positive/negative seen mask for all methods; first comparison freezes train history to isolate changing catalog',
       'content':'fit vocabulary/IDF/profiles using eligible train-period text only; new papers transform with frozen vectorizer, no future corpus IDF refit',
       'methods':['training_popularity','original_SAR','content','SAR_content_RRF'],
       'cold_item':'no train-positive score in SAR/popularity -> zero; apply common seen mask/tie rule; never remove zero-score papers from shared eligible catalog',
       'cold_user':'same no-eligible-train-like popularity fallback; global and catalog cold definitions both reported',
       'labels':'all future likes retained in metric denominator, including not-yet-public/unknown/outside candidates; attribution bins reported separately; do not silently drop inconsistent timestamps',
       'metrics':['macro Recall@10','NDCG@10','warm/cold user x warm/cold item','catalog/source coverage','fit memory and time','per-request P50/P95'],
       'tuning':'fusion chosen on declared tuning only, freeze before evaluation; current dev always descriptive; no fresh independent period found in current source',
       'scale_gate':'Original SAR Jaccard produces dense float64 item-item matrix. Do not fit all122697 without resource review; bounded catalog memory smoke or separately researched mature sparse CF needed before large-scale runs',
       'prospective_data':'Need newly arriving explicit feedback and observable request/exposure/first-ingest times; new anonymized logs need appropriate authorization. No scheduled collection started.'}
    save(REPORT/'proposed-expanded-contrast.json',future_protocol)
    verify_history()
    tested=re.search(r'Ran (\d+) tests in [^\n]+\n\s*\nOK',(REPORT/'tests-final.log').read_text(encoding='utf-8-sig'))
    if not tested:
        raise ValueError('Missing complete tests')
    table=[]
    for label in LABELS:
        vals=[]
        for split in ('tuning','dev'):
            v=coverage['splits'][split]['causes'].get(label,{'like_events':0,'event_fraction':0,'unique_papers':0})
            vals.extend([str(v['like_events']),f"{v['event_fraction']:.2%}"])
        table.append('| '+LABELS[label]+' | '+' | '.join(vals)+' |')
    expansion=coverage['expansion_date_counts']
    dev=coverage['splits']['dev']
    user_rows=[]
    for s in ('tuning','dev'):
        u=coverage['splits'][s]['users']
        user_rows.append(f"| {s} | {coverage['splits'][s]['users_with_future_likes']} | {u['cold_no_current_catalog_like']} | {u['cold_no_global_train_like']} | {u['no_train_feedback']} | {u['cold_no_current_catalog_like']-u['cold_no_global_train_like']} |")
    sample_table=[]
    for name,r in sample_stats.items():
        sample_table.append(f"| {name} | {r['rows']} | {r['has_title']} | {r['has_abstract']} | {r['has_dates']} | {r['has_reported_version_count']} |")
    scenarios_table=[]
    for name,r in scenario_costs.items():
        scenarios_table.append(f"| {name} | {r['items']:,} | {r['source_row_groups']} | {r['compressed_id_title_abstract_blocks_bytes']/2**20:.1f}MiB | 约{r['rough_minutes_at_observed_sample_file_rate']:.1f}分钟 | {r['dense_float64_sar_similarity_gib_lower_bound']:.2f}GiB |")
    audit_table=[
       f"| 有训练点赞的旧论文，日期筛选后潜在扩容 | {expansion['old_trainliked_latest_pre_cutoff']:,}篇，较现1781多{expansion['old_trainliked_latest_pre_cutoff']-1781:,}篇 | 首次≤最新版本日<训练截止；尚非历史入库证明，未全核标题摘要 | ID/标题/摘要列块约{scenario_costs['all_date_eligible_trainliked']['compressed_id_title_abstract_blocks_bytes']/2**20:.1f}MiB；单个SAR矩阵下限{scenario_costs['all_date_eligible_trainliked']['dense_float64_sar_similarity_gib_lower_bound']:.2f}GiB |",
       f"| 无训练点赞的截止前旧论文 | 日期符合的潜在{expansion['old_no_trainlike_latest_pre_cutoff']:,}篇 | 日期代理成立；尚未限定研究领域/逐篇文本完整性 | 不能按目标篇数线性估计下载量，需覆盖相应列块 |",
       f"| 日志期间新论文增量 | 首次版本日落在窗口{expansion['new_during_logged_window']:,}篇；最新版本日也不晚于日志末{expansion['new_latest_pre_log_end']:,}篇 | 后一个数量仍不保证各个更早推荐时点可用 | 需按日来源/版本与首次观察时间记录；未启动全量抓取 |",
       f"| 元数据/时间异常 | 未来点赞源ID/首次日期缺失0条；tuning异常{anomalies['tuning']['events']}、dev异常{anomalies['dev']['events']}条 | 源首次版本日晚于点赞，不静默改日期或剔除分母 | 异常归因本地完成，细项在忽略的data/ |"
    ]
    doc=f'''# 第十二阶段：候选覆盖、时间可用性与扩容成本审计

审计完成，无新推荐训练或dev选型。后段{dev['likes']:,}次真实点赞中，52.41%对应源首次版本日在训练截止后，27.03%落在Top-K截断旧论文，15.35%属于无训练点赞旧论文；当前目录占4.36%。这是候选可达性归因，不是算法Recall或扩容收益。全部未来点赞保留，包含异常时间记录。

## 交付审计表

| 漏召回原因 / 扩容方向 | 可扩容数量 / 诊断量 | 时间可信度 | 获取与计算成本 |
|---|---|---|---|
{chr(10).join(audit_table)}

“潜在”均指同一固定元数据快照的日期条件计数，**未按未来点赞选入候选，也未宣称这些论文全部有可用历史文本、符合研究领域或已经可推荐**。新论文数量也不是可直接叠加到历史每时点目录的数。

## 全部未来点赞的互斥归因

| 原因 | tuning点赞次数 | tuning比例 | dev点赞次数 | dev比例 |
|---|---:|---:|---:|---:|
{chr(10).join(table)}

两个划分分别46,352/49,533次点赞，26,124/30,222篇去重论文，源ID与首次日期均匹配。计数以用户—论文点赞事件为单位；同一论文可被多个用户点赞，不能把事件数当论文数。先判断缺失和源日期晚于事件，再判首次版本日与训练截止，再区分现目录/旧有赞被截断/旧无赞，互斥且总和等于完整分母。原2048中日期排除的267篇另外单列，未混入Top-K截断。已有32.25%训练获赞覆盖只是点赞加权诊断，不是宏平均Recall上限。

截止为{plan['cutoff']}，日志末为{plan['log_end']}。源日期来自OAI arXivRaw固定快照的first_version_date/latest_version_date，**是提交/处理日期，不能直接当作公告时刻、推荐请求时刻或历史已入库证明**。源日期和反馈时区未完全证明，naive时间按UTC只作一致记账。67篇源记录另保留早于ID月份的原预印本日期，因此不以ID月份替代日期字段。

dev有{dev['snapshot_text_time_flags'].get('snapshot_latest_after_feedback',0):,}次点赞对应的快照最新版本日晚于点赞；不能直接把这些当前摘要回填到当时。tuning/dev首次版本日晚于点赞异常分别{anomalies['tuning']['events']}/{anomalies['dev']['events']}次，训练集也有此类正/负反馈{train_anomalies.get('positive_events',0)}/{train_anomalies.get('negative_events',0)}次，保留原数据和完整计分分母。其差值范围、未知/版本标记见[审计聚合](stage12/cost-and-sample-aggregate.json)，未把日期字段当成绝对真值修正反馈。

## 用户冷启动与论文冷启动分开

| 划分 | 有未来点赞用户 | 现1781目录内无训练点赞 | 全训练集无任何点赞 | 无任何训练反馈 | 有训练点赞但因目录而冷 |
|---|---:|---:|---:|---:|---:|
{chr(10).join(user_rows)}

dev的{dev['items']['cold_like_events_no_trainlike']:,}次点赞（{dev['items']['cold_like_events_no_trainlike']/dev['likes']:.2%}）对应训练期从未获赞论文，涉及{dev['items']['cold_unique_no_trainlike']:,}篇；其中{dev['items']['cold_like_events_no_train_feedback']:,}次连训练负反馈也没有。无训练点赞不等于刚发表，旧无赞和新论文在上表分开。用户cold取现目录无点赞，论文cold取全训练期无点赞，两者交叉事件计数保存在[覆盖聚合](stage12/coverage-aggregate.json)。扩目录可恢复部分用户历史表示，不能宣称解决真正无历史用户。

## 不依赖未来点赞的文本与版本抽查

源扫描用原版PyArrow26.0.0/HfFileSystem0.36.2，固定[CC0元数据快照](https://huggingface.co/datasets/secemp9/arxiv-complete/tree/cee894837962fede5612cccf2a4c7cacf49b4c3a/metadata)，全3,148,796篇只取ID/两日期/版本计数。标题摘要只读取四个预定行组40/43/44/45，每个日期/train-like分层取SHA256(seed:ID)最小6篇，先固定协议再扫描，不以未来获赞、模型得分或结果好坏挑样本。24篇是有界分层核查，不能推断全目录文本覆盖率。

| 样本层 | 篇数 | 有标题 | 有摘要 | 有两日期 | 有版本计数 |
|---|---:|---:|---:|---:|---:|
{chr(10).join(sample_table)}

复用原版[arxiv.py](https://github.com/lukasschwab/arxiv.py/tree/09d1b8bc3c85c6334d480fa94c310c3b729b1d01)对每层首篇发一批明确v1请求，HTTP状态{official['statuses']}，取得{official['returned']}份官方v1元数据，完整版本1身份{official['exact_version1']}份，首次日期与快照一致{official['first_date_matches_snapshot']}份；快照标题/摘要与v1逐字一致{official['snapshot_text_exact_same_as_v1']}份、空白归一一致{official['snapshot_text_whitespace_same_as_v1']}份。不同版本文字差异应保留，不能用最新文本替换v1。n_versions始终只作源报告的版本数量，不猜成版本号。官方v1可取回比仅有快照日期更可审计，但本次获取发生在2026年，仍未取得2024/2025的历史系统入库或精确公告时间。

API只发一批、num_retries0、单连接与3.1秒限速，遇429即停，无切换主机绕限流。本次状态与失败原因原样保留。元数据CC0不授权论文全文；没有下载PDF/LaTeX。组件源码、许可、备选和适配边界见[开源审计](stage12/upstream-audit.json)。

## 真实获取成本与扩容成本边界

全量轻量列压缩块35,548,361字节；实际Arrow read返回{costs['light']['arrow_returned_bytes']:,}字节、{costs['light']['file_read_calls']}次，分组阶段{costs['light']['invocation_wall_seconds']:.2f}秒。四组样本文本列块99,101,217字节，实际返回{costs['sample']['arrow_returned_bytes']:,}字节、{costs['sample']['file_read_calls']}次、{costs['sample']['invocation_wall_seconds']:.2f}秒。4个公共镜像读取器，包含各句柄重复footer等读取；文件read返回字节**不包含HTTP/TLS/Hub元数据请求和失败未返回的传输量，不是总网络流量**。样本读取发生TLS EOF，保留HF原生重试日志及已完成分组缓存。官方v1批次另耗时{official['seconds']}秒。

Parquet按列块/行组读取，24篇分散样本也需读取4组约99MB；不能拿目标篇数占比乘整文件大小估下载量。以下候选成本场景只用训练点赞频次和源日期定义，未用未来标签挑规模；列块大小是读取相应原文件列块的压缩字节下界，实际还含footer、重试与协议开销。

| 训练期日期可用场景 | 篇数 | 涉及源行组 | ID/标题/摘要列块压缩量 | 样本速率粗估读取时间 | 单个SAR相似度矩阵最低内存 |
|---|---:|---:|---:|---:|---:|
{chr(10).join(scenarios_table)}

时间列仅为压缩列块字节数除以本次样本file.read返回速率；未实际读取上述扩容场景，不是时延承诺或统计区间。网络、缓存、分组数、TLS重试及额外文件/API开销都可能改变结果。

原版SAR Jaccard在python_utils.py返回稠密数组，当前float64适配的单个矩阵至少8×N²字节，**不含共现、分母和其他拟合临时数组**。因此不能直接把现实现扩到12万篇；应先做有预算的小目录内存试跑，或另行调研成熟稀疏协同组件。未执行大目录拟合，以上是源码支持的容量估算，不是实测峰值。整个源文件ID/标题/摘要列块压缩合计{cost_detail['source_all_id_title_abstract_compressed_bytes']/2**20:.1f}MiB。当前阶段无扩容后推荐耗时或质量结论。

## 后续对照设计与独立时间段

当前[Scholar Inbox主分支](https://github.com/avg-dev/scholar_inbox_datasets/tree/92b0fac32110b1243081476f69607cf51aa71ad4)仍是已经使用过的92b0fac32110b1243081476f69607cf51aa71ad4；本来源没有找到新的未使用时间段。不能把旧dev重新切一段称为独立测试。后续需要该来源真正新增且晚于2025-02-23的反馈，或得到授权的新日志；不同用户/论文命名空间的新数据也不能直接拼接为原用户后续。

后续协议为设计草案：[proposed-expanded-contrast.json](stage12/proposed-expanded-contrast.json)。每个回放时点四方法共享完全相同的可用目录与原train历史、正负seen过滤；第一轮固定历史以隔离目录变化。历史版本/公告证据和最新快照日期代理分开评价，前瞻系统记录first-observed-ingest，未来点赞仅作诊断/评价，不决定候选纳入。内容词表/IDF/画像只拟合训练期文本，新论文只transform。无训练正反馈的SAR/流行度项零分并保留共同候选；冷用户统一回退，相等分数按固定ID。报告完整分母Recall/NDCG、用户×论文冷热、覆盖及P50/P95成本，融合只在声明的tuning选择后冻结。新日志未取得前仍只能描述性对照，不启动新模型选型。

## 验证与复现

{int(tested.group(1))}项测试通过；63个源分组hash、3,148,796行总数、固定抽样完整重现、24篇轻重列一致与身份链接、官方响应hash、全部{sum(validation.values()):,}次未来点赞逐条归因与用户/论文冷热计数重核、阶段3—11冻结检查均通过。细粒度派生反馈/样本/候选成本场景仅在被忽略的data/stage12-audit，公开报告只存聚合；源缓存在.cache/stage12，无新依赖安装或旧实验覆盖。完整性收据：[final-validation.json](stage12/final-validation.json)。

解释器沿用`.cache/stage6-env/Scripts/python.exe`。已完成的冻结/归因/官方探测拒绝覆盖；缓存源读取可断点续跑。顺序为`python -m scripts.read_catalog_audit --phase layout`、`python -m scripts.audit_catalog_coverage --phase freeze`、`python -m scripts.read_catalog_audit --phase light`、`python -m scripts.audit_catalog_coverage --phase build`、`python -m scripts.read_catalog_audit --phase sample`、`python -m scripts.probe_catalog_versions`，最后`python -m scripts.make_stage12_report`重新验证并生成聚合报告。运行目录为本项目；网络读取仅公开固定来源，既有官方冷却标记会被检查。
'''
    Path('reports/阶段12_候选覆盖与时间入库审计.md').write_text(doc,encoding='utf-8')
    save(REPORT/'final-validation.json',{'tests':int(tested.group(1)),'future_likes_recounted':validation,
          'source_rows':source_rows,'sample_rows_checked':len(sample_rows),'sampler_reproduced':True,
          'independent_vectorized_attribution':'pandas masks match all diagnostic event causes',
          'independent_arrow_expansion_counts':dict(expansion_check),
          'official_version1_records':official['exact_version1'],'historical_stages3_11':'unchanged',
          'no_expanded_ranking_runs':True,'new_independent_period_found':False,
          'outputs':{p.name:digest(p) for p in REPORT.glob('*.json') if p.name!='final-validation.json'},
          'data_assets':{p.name:digest(p) for p in DATA.glob('*.json')},
          'sample_source_assets':{str(p):digest(p) for p in (CACHE/'sample').glob('*') if p.is_file()},
          'official_raw_assets':{r['raw_path']:r['raw_sha256'] for r in api.get('requests',[])},
          'code_assets':{str(p):digest(p) for p in (Path('gsearch/catalog_audit.py'),Path('scripts/read_catalog_audit.py'),Path('scripts/audit_catalog_coverage.py'),Path('scripts/probe_catalog_versions.py'),Path('scripts/make_stage12_report.py'),Path('tests/test_catalog_audit.py'))}})
    print(json.dumps({'tests':int(tested.group(1)),'source_rows':source_rows,'likes_recounted':validation,
                     'sample':sample_stats,'official':official,'cost_scenarios':scenario_costs}),flush=True)

if __name__=='__main__':
    main()
