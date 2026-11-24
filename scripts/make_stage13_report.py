"""Source/version, resource, replay and historical validation; aggregate-only report."""
import hashlib
import json
from pathlib import Path
import re

import numpy as np

from gsearch.expansion_data import DATA,ROOT,CACHE,TIERS,save,read
from gsearch.catalog_audit import digest,stamp
from gsearch.benchmark_expansion import check_plan,pick,SINGLES,FUSIONS,events
from gsearch.expansion_recommendation import load,signature
from scripts.validate_expansion import validate_corpus,validate_outputs
from scripts.make_stage9_report import paired

def historical() -> None:
    from scripts.make_stage12_report import verify_history
    verify_history()
    base=Path('reports/stage12');r=read(base/'final-validation.json')
    if any(digest(base/n)!=v for n,v in r['outputs'].items()):raise ValueError('Stage12 outputs changed')
    for key in ('code_assets','sample_source_assets','official_raw_assets'):
        if any(digest(Path(n))!=v for n,v in r[key].items()):raise ValueError('Stage12 source/data provenance changed')
    if any(digest(Path('data/stage12-audit')/n)!=v for n,v in r['data_assets'].items()):raise ValueError('Stage12 local derived assets changed')

def main() -> None:
    plan=check_plan();lock=read(ROOT/'locked-before-dev.json')
    if lock['plan_sha256']!=digest(ROOT/'evaluation-plan.json') or any(digest(ROOT/n)!=v for n,v in lock['tuning_results_sha256'].items()):
        raise ValueError('Tuning selection lock mismatch')
    source=validate_corpus()
    results,users,checked=validate_outputs()
    for n in TIERS:
        tuning={m:results[n,'tuning',m] for m in (*SINGLES,*FUSIONS)}
        chosen=max(FUSIONS,key=lambda m:(*pick(tuning[m]),FUSIONS[m] in (0,1),-FUSIONS[m]))
        best=max(SINGLES,key=lambda m:(*pick(tuning[m]),-SINGLES.index(m)))
        if lock['tiers'][str(n)]!={'alpha':FUSIONS[chosen],'selected':chosen,'best_single':best}:raise ValueError('Selection rule not reproduced')
    from gsearch.content_recommendation import sklearn_runtime
    sklearn_runtime();from threadpoolctl import threadpool_limits
    replay={}
    with threadpool_limits(limits=1):
        for n in TIERS:
            model=load(n)
            if signature(model)!=read(ROOT/f'resource-{n}.json')['model_signature']:raise ValueError('Fitted model signature differs')
            requests=0
            for split in ('tuning','dev'):
                f=events(split)
                # Fixed hash sample, independent of success/rank; replay native uncached path.
                picks=sorted(range(len(f)),key=lambda i:hashlib.sha256(('stage13-replay:'+f.at[i,'user_id']+':'+f.at[i,'time']).encode()).hexdigest())[:8]
                methods=(*SINGLES,*FUSIONS) if split=='tuning' else (*SINGLES,'hybrid')
                for method in methods:
                    with np.load(DATA/f'{n}-{method}-{split}.npz',allow_pickle=False) as raw:pred=raw['indices']
                    mode='hybrid' if method in FUSIONS or method=='hybrid' else method
                    alpha=FUSIONS.get(method,lock['tiers'][str(n)]['alpha'])
                    for i in picks:
                        row=f.iloc[i]
                        expected=model.rank_indices(row.user_id,row['at'].to_pydatetime(),mode,10,alpha)
                        if not np.array_equal(pred[i,:len(expected)],expected):raise ValueError('Uncached ranking replay differs')
                        requests+=1
            replay[str(n)]=requests
            del model
    comparisons={}
    for n in TIERS:
        best=lock['tiers'][str(n)]['best_single']
        comparisons[str(n)]={'hybrid_minus_tuning_best_single':paired(users[n,'dev','hybrid'],users[n,'dev',best])}
    comparisons['10000_minus_1000']={m:paired(users[10000,'dev',m],users[1000,'dev',m]) for m in (*SINGLES,'hybrid')}
    save(ROOT/'paired-aggregate.json',comparisons)
    # Run real tool objects, source/train-only integration-user selection, no heldout relevance cherry-pick.
    from gsearch.expansion_discovery import ExpansionSession,make_tools
    with threadpool_limits(limits=1):
        model=load(10000)
        user=min(model.users,key=lambda u:hashlib.sha256(('stage13-demo:'+u).encode()).hexdigest())
        session=ExpansionSession(model,user,read(ROOT/'admission-plan.json')['end'],'hybrid',lock['tiers']['10000']['alpha'])
        tools={t.name:t for t in make_tools(session)}
        selected=tools['recommend_papers'](k=3)
        original=tools['read_paper'](doc_id=selected['papers'][0]['doc_id'])
        save(DATA/'pipeline-demo.json',{'selection':'minimum fixed hash of train-profile users; no future relevance labels used',
           'trace':session.trace,'source_verified':original['source_verified']})
        demo={'tools':[r['tool'] for r in session.trace],'source_verified':original['source_verified'],'version':original['version'],
            'returned':len(selected['papers']),'semantic_stance_verified':False,
            'selection':'train-only fixed hash user, integration proof only'}
        initial=int((model.available<=model.cutoff.timestamp()).sum())
        final=int((model.available<=stamp(read(ROOT/'admission-plan.json')['end']).timestamp()).sum())
    save(ROOT/'pipeline-demo-aggregate.json',demo)
    historical()
    tested=re.search(r'Ran (\d+) tests in [^\n]+\n\s*\nOK',(ROOT/'tests-final.log').read_text(encoding='utf-8-sig'))
    if not tested:raise ValueError('Final tests not passed')
    resources={str(n):read(ROOT/f'resource-{n}.json') for n in TIERS}
    gates=read(ROOT/'resource-gates.json')
    gate_by_tier={g['tier']:g for g in gates}
    if not all(g['passed'] for g in gates):raise ValueError('Resource gate failure')
    resource_rows=[];quality_rows=[];cold_rows=[];tuning_rows=[]
    for n in TIERS:
        r=resources[str(n)];s=lock['tiers'][str(n)]
        resource_rows.append(f"| {n:,} | {r['fit']['warm_items_in_sar']:,} | {r['fit_wall_seconds']:.2f} | {gate_by_tier[n]['wall_seconds']:.2f} | {r['fit_phase_peak_working_set_bytes']/2**30:.3f} | {r['fit_phase_peak_commit_counter_bytes']/2**30:.3f} | {r['fit']['sar_matrix_bytes']/2**20:.1f} |")
        for method,alpha in FUSIONS.items():
            q=results[n,'tuning',method]['summary']
            tuning_rows.append(f"| {n:,} | {alpha:g} | {q['recall@10']:.6f} | {q['ndcg@10']:.6f} |")
        latency=read(ROOT/f'{n}-latency-dev.json')
        for method in (*SINGLES,'hybrid'):
            r=results[n,'dev',method];q=r['summary'];l=latency['methods'][method]
            quality_rows.append(f"| {n:,} | {method} | {q['recall@10']:.6f} | {q['ndcg@10']:.6f} | {q['eligible_gold_event_fraction']:.2%} | {q['catalog_coverage']:.2%} | {l['mean_ms']:.2f} / {l['p95_ms']:.2f} |")
            cross=r['event_cold_cross'];cold_events=[v for key,v in cross.items() if key.endswith('cold_item')]
            denom=sum(v['events'] for v in cold_events)
            cold_recall=sum(v['events']*(v['recall'] or 0) for v in cold_events)/denom if denom else 0
            cold_ndcg=sum(v['events']*(v['ndcg'] or 0) for v in cold_events)/denom if denom else 0
            cold_rows.append(f"| {n:,} | {method} | {q['warm_users']} / {q['cold_users']} | {r['user_groups']['warm_user']['ndcg']:.6f} | {r['user_groups']['cold_user']['ndcg']:.6f} | {cold_recall:.6f} / {cold_ndcg:.6f} |")
    selected=lock['tiers']['10000'];best=selected['best_single']
    primary=comparisons['10000']['hybrid_minus_tuning_best_single']
    growth=comparisons['10000_minus_1000']['hybrid']
    def delta_line(name: str,comp: dict) -> str:
        rows=[]
        for metric in ('recall','ndcg','mrr'):
            x=comp[metric];lo,hi=x['bootstrap_95_percentile_interval']
            rows.append(f"| {name} | {metric} | {x['mean_delta']:+.6f} | [{lo:+.6f}, {hi:+.6f}] | {x['wins']}/{x['losses']}/{x['ties']} |")
        return '\n'.join(rows)
    endpoint=selected['alpha'] in (0,1)
    verdict=('1万目录tuning选择端点，所谓混合实际退化为单方法，不能声称融合收益。' if endpoint else
             '1万目录tuning选择内部融合权重，收益需结合下方主比较区间判断，不能只看点估计。')
    source_period=read(Path('reports/stage12/new-period-source-check.json'))
    summary=results[10000,'dev','hybrid']['summary']
    doc=f'''# 第十三阶段：1万篇受控扩容与时序推荐链路

已交付固定版本入库、共享逐时点目录、原SAR/内容/融合推荐和原摘要读取链路。1千→5千→1万全部资源门槛通过，四方法完整tuning后统一冻结再评价dev。1万目录SAR权重{selected['alpha']:g}，tuning最佳单方法{best}。{verdict} dev仍是重复使用的描述性对照，不是新独立测试。

```mermaid
flowchart LR
 A[训练反馈与固定源ID池] --> B[官方v1与日期/领域校验]
 B --> C[共享as-of候选目录]
 C --> D[流行度/SAR/内容/RRF]
 D --> E[推荐论文ID与版本]
 E --> F[原响应hash与原版解析器读取摘要]
```

## 目录、版本和时间边界

1万预算固定8000篇训练有赞、1000篇无训练点赞旧论文、1000篇逐日进入的无训练点赞论文。全部选入官方明确v1标题/摘要及v1实际category：cs.AI/CL/CV/IR/LG/NE/RO、stat.ML。warm按train频次与ID，oldcold按源ID固定hash，新论文每提交日hash池前150中最多9篇、全期cap1000，不读未来点赞。1千/5千嵌套为800/100/100与4000/500/500，新入库每天最多1/5篇；语料和整个准入顺序已从原响应与原train完整重现。

采集时旧格式ID混合查询出现HTTP500，现代子组38/38成功，旧格式单篇既有成功也有失败，不能笼统称旧论文不存在。**在任何tuning/resource拟合前，范围修订为现代arXiv ID（2007-04起）**；原计划、定位响应、断点和[范围修订](stage13/identifier-scope-amendment.json)保留，当时8000warm/39oldcold全为现代ID，无需替换已有记录。剩余5xx拆分到单ID后只记未取得/状态未知；官方429立即停并至少冷却300秒，之后间隔由3.1提高至5.1秒，未换主机绕限流。全部原始未来标签含旧格式/范围外论文仍在分母。

available_at=官方v1提交日结束再延迟24h，按UTC记账。**这是显式可用性代理，不是已证明的历史公告或实际入库时间**，当今源框架完整性也属回溯快照假设。初始目录{initial}篇，日志末可用{final}篇；每请求先过滤available_at，再统一过滤所有train正负seen，然后排序和RRF，未入库论文不能推荐或读取。v1原文不会被后续版本覆盖。元数据描述性字段CC0不授权PDF/fulltext，本轮只读取原摘要。

“新入库”按可用性代理划分，其中{source['new_cohort_published_after_train_cutoff']}篇官方v1首次提交日在训练截止之后，其余是截止前近期提交、代理入库延后至截止之后的论文；不把二者混称为都在截止后首次发表。采集中本机代理端口曾关闭，验证连通后仅本次请求Session使用--direct连接同一官方端点，TLS/限速/冷却不变，未改系统代理，见route-recovery.json。

## 成熟组件与实际获取成本

复用原MIT arxiv.py09d1b8bc Client/Result/lxml解析，原MIT Recommenders SAR ba49f480，原BSD3 sklearn1.9.1向量化/归一化/余弦，以及原BSD3 psutil7.2.2 Windows原生峰值计数。未重写Parquet、CF、TFIDF、余弦或Agent循环，也没有升级共享CUDA环境。来源和适配边界见[开源审计](stage13/upstream-audit.json)。

12篇明确版本预检全部返回v1后才批量获取。最终{source['verified_records']:,}篇逐条重解析官方原始响应，身份/版本/标题/摘要/category/日期/hash一致。源请求共{source['source_requests']}次，HTTP统计{source['http_status_counts']}，响应body累计{source['response_body_bytes']/2**20:.2f}MiB；这是响应体字节，不含HTTP/TLS开销。记录的主批次调用累计{source['recorded_native_request_seconds']/60:.2f}分钟（含原客户端限速等待，未完整计入诊断、冷却、人工开发等待等），不是端到端耗时承诺。失败和候选相关日志均在忽略的data/或.cache/，公开报告不散发训练知情ID列表。

## 逐级资源门槛

三个规模各用独立进程、CPU单数值线程。门槛为工作集6GiB、Windows峰值提交计数8GiB、180秒超时，父进程50ms守护。使用psutil原生peak_wset/peak_pagefile计数，记录至拟合结束的累计峰值及完整验证阶段峰值，不用稀疏RSS快照冒充峰值。装载+拟合秒不含解释器/运行时导入启动，另列子进程启动至退出的总墙钟；字段级SAR/TFIDF/画像时长在JSON中。峰值包含进程导入及拟合临时数组。

| 候选预算 | SAR训练有赞项 | 装载+拟合秒 | 子进程总墙钟秒 | 拟合阶段峰值工作集GiB | 峰值提交计数GiB | 实际SAR矩阵MiB |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(resource_rows)}

1万候选中2000篇没有训练正反馈，SAR只需8000×8000矩阵；仍在共同候选中的冷论文协同分和训练流行度为0，不伪造交互或删除冷论文。该规模的矩阵内存与“1万篇全有训练赞”的0.75GiB估算口径不同。完整进程峰值、门槛和模型签名见[资源收据](stage13/resource-gates.json)。

## 共同历史和评价定义

四方法使用相同原train历史截止和正负seen过滤；SAR与内容兴趣使用相同eligible train-positive历史。第一轮不回写tuning/dev反馈历史，旨在受控比较目录条件，不代表在线反馈更新。词表/IDF只fit初始可用v1文本，未来1000篇只transform，未来文本投毒测试证明不会改变过去词表/IDF/画像/推荐。冷用户四方法同流行度，零内容向量显式回退。等分按基础论文ID，RRF常数60，端点0/1完全等于内容/SAR分支。

每条原始未来正反馈时刻前预测该条目标，输出Top10；每事件singleton Recall/NDCG/MRR，先在用户内平均再跨用户平均。完整tuning46,352/dev49,533条点赞和3571/3587用户均保留，范围外/尚未可用/日期异常的gold仍计miss。**这是以已观测正反馈事件为回放点的条件排序，不是实际请求/曝光日志、CTR或线上实验；新NDCG不能直接与阶段11整期单列表NDCG比较。** 1千/5千/1万重新按同一协议评价。

质量回放用原生scorers批量64用户并复用固定历史分数/每日排名；后续延迟独立对256条固定hash事件无缓存batch1测量，轮换方法顺序，绝不拿缓存回放耗时当单请求延迟。范围、代码、数据、资源签名在evaluation-plan冻结；所有tier的融合仅tuning选择后统一锁定才进入dev。

## tuning与冻结参数

| 候选预算 | SAR权重 | Recall@10 | NDCG@10 |
|---|---:|---:|---:|
{chr(10).join(tuning_rows)}

各tier选择为{lock['tiers']}。主比较是该tier选定混合相对tuning最佳单方法，禁止看dev重选。原始端点和所有失败/负面结果保留。

## 后段四组质量、覆盖与耗时

“gold可达”按点赞事件数计目标当时在目录且可用的比例，不是宏平均Recall上限；“推荐覆盖”分母为该tier全期目录预算。耗时列为独立256事件无缓存每请求均值/P95毫秒，单次本地测量受系统负载影响。

| 候选预算 | 方法 | 用户宏Recall@10 | 用户宏NDCG@10 | gold当时可达 | 推荐覆盖 | 均值 / P95 ms |
|---|---|---:|---:|---:|---:|---:|
{chr(10).join(quality_rows)}

## 用户与论文冷启动

用户cold=当前tier没有训练有赞历史，论文cold=全原train没有任何点赞，两者不等同。下表用户NDCG为用户宏平均，冷论文两指标为全部冷论文目标事件微平均，包含未纳入候选的冷论文。跨目录规模时用户冷热组成员会改变，组内分数变化也含构成变化；完整四交叉计数和指标在各方法JSON，不能把目录可达子集的好结果替代全分母。

| 候选预算 | 方法 | 暖/冷用户数 | 暖用户NDCG | 冷用户NDCG | 冷论文事件Recall / NDCG |
|---|---|---:|---:|---:|---:|
{chr(10).join(cold_rows)}

## 配对差异与局限

用户bootstrap10000次、固定seed，区间仅描述用户重采样变化，不覆盖训练/源采集/目录和版本时间代理/重复dev选型偏差。扩容差是整个目录条件的差异：同时改变可达候选、eligible训练历史、TFIDF拟合语料和各自tuning权重，**不能全部归因于新增论文数量，更不是单一机制的因果效应**。

| 比较 | 指标 | 平均差 | bootstrap95%区间 | 胜/负/平用户 |
|---|---|---:|---|---|
{delta_line('10000混合 - tuning最佳'+best,primary)}
{delta_line('10000混合 - 1000混合',growth)}

所有单方法扩容差和各tier主比较见[配对聚合](stage13/paired-aggregate.json)。当前同源main仍为已使用commit{source_period['head']}，没有新的独立显式评分时间段，dev继续描述性；不能重切旧dev冒充未见测试。阶段12已报告源时间异常，原记录不改。

## 可运行链路与验证

真实smolagents工具recommend_papers→read_paper已完成，返回{demo['returned']}篇、读取v{demo['version']}摘要并核对官方原body/原解析器输出。集成用户只从train用户固定hash选取，不看未来命中；轨迹在data/stage13-expansion/pipeline-demo.json，不据单例声称Agent或科学论断验证收益。

```powershell
& ".cache/stage6-env/Scripts/python.exe" -m gsearch.expansion_discovery --tier 10000 --user USER_ID --at "2025-02-23T05:28:26.401006+00:00" --method hybrid --k 3 --read-top1 --output data/my-expansion-demo.json
```

{int(tested.group(1))}项测试通过，全部36份原始NPZ排名重计分、完整gold/seen/可用时点/冷热/覆盖、端点与冷用户一致性、全1万源v1重解析、原准入重现、嵌套目录、每tier{next(iter(replay.values()))}次原生无缓存排名抽查、拟合签名与阶段3—12冻结检查通过。NPZ用allow_pickle=False读取；无外部pickle。用户派生数据/预测/候选/详细日志仅在忽略的data/，Scholar Inbox CC BY-NC-ND4.0本地非商业及不分发衍生明细边界不变。收据：[final-validation.json](stage13/final-validation.json)。复现顺序与冻结/续跑约束见README。
'''
    Path('reports/阶段13_万篇扩容与时序推荐.md').write_text(doc,encoding='utf-8')
    save(ROOT/'final-validation.json',{'tests':int(tested.group(1)),'source':source,'raw_outputs_rescored':checked,
       'native_uncached_rank_replay':replay,'historical_stages3_12':'unchanged','real_tool_demo':demo,
       'identifier_scope':'modern IDs, all original heldout gold retained','dev_descriptive_only':True,
       'outputs':{p.name:digest(p) for p in ROOT.glob('*.json') if p.name!='final-validation.json'},
       'data_assets':{p.name:digest(p) for p in DATA.iterdir() if p.is_file() and p.suffix in ('.json','.npz')},
       'code_assets':{str(p):digest(p) for p in [Path('gsearch')/f for f in ('expansion_data.py','expansion_recommendation.py','benchmark_expansion.py','expansion_discovery.py')]+[Path('scripts')/f for f in ('fetch_expansion_versions.py','expansion_resources.py','validate_expansion.py','make_stage13_report.py','run_expansion_pipeline.py')]+[Path('tests/test_expansion.py')]}})
    print(json.dumps({'tests':int(tested.group(1)),'corpus':source,'selected':lock['tiers'],'dev10000':summary,'primary':primary,'growth':growth}),flush=True)

if __name__=='__main__':main()
