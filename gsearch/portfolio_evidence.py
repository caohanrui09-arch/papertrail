"""Source-linked facts only; no re-evaluation, tuning or new quality claims."""
import json
from pathlib import Path
from .quality_protocol import digest,save

REPORT=Path('reports/stage22')


def collect() -> dict:
    claims={}
    def add(key: str,path: str,pointer: str) -> None:
        value=json.loads(Path(path).read_text(encoding='utf-8'))
        for part in pointer.strip('/').split('/'):
            value=value[part.replace('~1','/').replace('~0','~')]
        claims[key]={'value':value,'source':path,'json_pointer':pointer,'sha256':digest(Path(path))}
    for model in ('numeric','title','bm25'):
        for metric in ('recall@10','ndcg@10','judged_queries'):
            add(f'search.{model}.{metric}',f'reports/stage4/{model}-dev.json','/summary/'+metric)
    for field in ('passed','short_minus_full','short_over_full'):
        add('short_id.'+field,'reports/stage8/tuning-decision.json','/'+field)
    for field in ('candidates','warm_items_in_sar','future_transform_only_documents','vocabulary'):
        add('corpus.'+field,'reports/stage13/resource-10000.json','/fit/'+field)
    for method in ('content','rrf','plain','gated'):
        path=f'reports/stage15/{method}-dev.json'
        for metric in ('recall@10','ndcg@10','users','positive_events','catalog_coverage'):
            add(f'recommend.{method}.{metric}',path,'/summary/'+metric)
        for group in ('warm_item','cold_item'):
            for field in ('hits','events'):
                add(f'recommend.{method}.{group}.{field}',path,f'/event_groups/{group}/{field}')
    for kind in ('original','indexed'):
        add('performance.hybrid.'+kind,'reports/stage14/benchmark.json',f'/paired_uncached_latency/hybrid/{kind}/mean_ms')
    path=Path('reports/stage14/benchmark.json');raw=json.loads(path.read_text());records=raw['exact_replay']
    claims['performance.exact_rankings']={'value':sum(v['events'] for v in records.values()),'source':str(path),
        'json_pointer':'/exact_replay','derivation':'sum of events across12 exact_replay entries','sha256':digest(path)}
    claims['performance.changed_rankings']={'value':sum(v['changed_events'] for v in records.values()),'source':str(path),
        'json_pointer':'/exact_replay','derivation':'sum of changed_events','sha256':digest(path)}
    for field in ('verified_bundle_assets','physical_second_machine_tested','frozen_model_signature_exact'):
        add('reproduction.'+field,'reports/stage17/isolation-summary.json','/'+field)
    for field in ('assistant_draft_queries','human_authored_queries','human_judgments','blind_pairs'):
        add('annotation.'+field,'reports/stage20/final-validation.json','/'+field)
    for method in ('fixed','llm_agent','constrained'):
        for field in ('tasks','completed','task_success','input_tokens','output_tokens','mean_seconds'):
            add(f'agent.{method}.{field}','reports/stage21-isolated/evaluation-summary.json',f'/methods/{method}/{field}')
    add('agent.guards_pass','reports/stage21-isolated/evaluation-summary.json','/engineering_guards_all_pass')
    add('agent.invalid_v1_used','reports/stage21-isolated/final-validation.json','/invalid_v1_metrics_used_as_evidence')
    return {'scope':'Frozen historical results, not new evaluation. SciFact and arXiv are separate; dev reused; source citation is not relevance.',
        'claims':claims,'defaults':{'search':'native SQLite FTS5 BM25 on arXiv','recommendation':'content','workflow':'fixed'},
        'research_only':['SciFact T5 variants','cold_aware alpha0.25','original and constrained LLM dispatch']}


def markdown(evidence: dict) -> str:
    c=evidence['claims'];v=lambda key:c[key]['value']
    rows=[]
    for model in ('numeric','title','bm25'):
        rows.append(f"| {model} | {v('search.'+model+'.recall@10'):.6f} | {v('search.'+model+'.ndcg@10'):.6f} |")
    rec=[]
    for method in ('content','rrf','plain','gated'):
        rec.append(f"| {method} | {v('recommend.'+method+'.recall@10'):.6f} | {v('recommend.'+method+'.ndcg@10'):.6f} | {v('recommend.'+method+'.cold_item.hits')}/{v('recommend.'+method+'.cold_item.events')} | {v('recommend.'+method+'.warm_item.hits')}/{v('recommend.'+method+'.warm_item.events')} |")
    agent=[]
    for method in ('fixed','llm_agent','constrained'):
        prefix='agent.'+method+'.'
        agent.append(f"| {method} | {v(prefix+'task_success')}/{v(prefix+'tasks')} | {v(prefix+'completed')}/{v(prefix+'tasks')} | {v(prefix+'input_tokens')+v(prefix+'output_tokens')} | {v(prefix+'mean_seconds'):.3f} |")
    return f'''# 核心算法证据与最终取舍

本表由 `gsearch.portfolio_evidence` 读取既有冻结JSON生成。每个事实的源路径、JSON Pointer和SHA在[机器可读索引](../reports/stage22/evidence-index.json)。本轮不新增训练或选型。指标只在同一表的原协议内比较。

## 生成式检索：独立SciFact实验

5183篇闭集文档；T5 query→DocID，索引/查询双任务、合法ID前缀树和原生beam解码。标题前缀ID为规则构造，不是学习到的语义码本。文档内容可参与索引训练，查询监督仅用train；公开dev300中188条有证据参与质量指标，112条无证据排除。

| 阶段4方法 | Recall@10 | NDCG@10 |
|---|---:|---:|
{chr(10).join(rows)}

标题ID提高了相对数字ID的Recall，但未超过BM25。阶段8同基础T5、同抽样顺序/4000步/beam10，完整与压缩ID目标直接保存token IDs；197个别名文本重分词不稳定。短ID tuning NDCG差={v('short_id.short_minus_full')['ndcg']:.6f}，输出token比={v('short_id.short_over_full')['returned_tokens']:.3f}，耗时比={v('short_id.short_over_full')['mean_seconds']:.3f}，质量保护未过，**未跑dev**。短路径节省工作不等于整体方案可替换。

保留T5实验和负结果；万篇服务搜索使用BM25，未把SciFact微调权重迁移成万篇生成式召回。[阶段4](../reports/阶段4_标题ID生成检索.md) · [阶段8](../reports/阶段8_完整与短ID匹配训练.md)。

## 推荐与冷启动：共同万篇v1、完整未来点赞分母

8000篇训练有赞、1000篇无赞旧论文、1000篇按时点进入。SAR复用物品共现/Jaccard实现；内容法以冻结标题/摘要TF-IDF和训练点赞画像做余弦推荐。train正负seen统一过滤，负反馈不作为SAR负权重；新文档只transform，不重拟合词表/IDF，冷用户沿原流行度回退。

阶段15 dev为{v('recommend.content.users')}用户、{v('recommend.content.positive_events')}个未来正反馈事件；每事件目标singleton Recall/NDCG，先用户内后跨用户宏平均。目录外/未入库目标仍计miss，论文组是事件微平均；这不是普通整期列表NDCG。dev多轮使用，仅描述性。

| 方法 | Recall宏平均 | NDCG宏平均 | 冷论文命中/事件 | 热论文命中/事件 |
|---|---:|---:|---:|---:|
{chr(10).join(rec)}

原RRF把协同0分冷项放入尾部并列排名，又削弱仅有内容的证据。项目适配在当前eligible目录调用原生minmax_scale：

```text
score=(alpha*support*z_cf+(1-alpha)*z_text)/(alpha*support+1-alpha)
support=该论文是否在冻结SAR训练词表中；不等同于该用户协同得分是否非零
```

alpha0.25在tuning选择后冻结；plain同归一化/同alpha但不门控，用于分离门控贡献。冷热用户/论文分开；同进程成本和热项保护通过，仍保留content默认，cold_aware显式研究使用。不能把冷事件命中20→50写成新论文篇数、用户数、CTR或独立泛化收益。[阶段15原报告与全部组](../reports/阶段15_冷论文融合归因与对照.md)。

## 工程：排名不变的过滤加速

train-only稀疏seen位置、一次timestamp和原生NumPy掩码，复用原评分/稳定并列规则。{v('performance.exact_rankings')}个事件—方法Top10排名核对，改变{v('performance.changed_rankings')}；固定请求配对样本中原融合均时{v('performance.hybrid.original'):.2f}→{v('performance.hybrid.indexed'):.2f}ms。时间排除装载/拟合/原文读取，不能与Agent端到端秒数或其他阶段机器状态直接相减。[阶段14](../reports/阶段14_推荐请求无损加速.md)。

## Agent：实际执行约束与模型调度分开

统一万篇BM25/推荐/原摘要API接入原生smolagents。阶段21先4 tuning再冻结，12个已使用受控显式意图任务的有效isolated-v2结果：

| 方法 | 目标成功 | 协议完成 | 总LLM token | 平均秒 |
|---|---:|---:|---:|---:|
{chr(10).join(agent)}

控制器不看goldID、不补参数或自动提交；动态schema提示＋运行时合法动作/成员/预算检查，非token级约束解码。约束减少token并提高成功数，但未过可靠性/耗时门槛，默认fixed并结束本轮优化。首批共享schema污染比较全作废；有效组每请求前后检查默认schema不变。不能将规则的收益归因于模型推理能力。[阶段21](../reports/阶段21_状态约束Agent可靠性与成本.md)。

## 可复现与仍缺的证据

同机新CPU运行时迁移{v('reproduction.verified_bundle_assets')}项资产，签名/三路轨迹一致；真实第二台机器={v('reproduction.physical_second_machine_tested')}。阶段20准备{v('annotation.assistant_draft_queries')}条assistant_draft需求、{v('annotation.blind_pairs')}盲对，封存时真人原创问题/标签均0；质量NDCG/MRR未计算。它们不能补成真实用户或独立相关性证据。[隔离复现](ISOLATED_REPLAY.md) · [标注准备](QUALITY_ANNOTATION.md)。

## 复用和本项目工作

直接复用Transformers Seq2SeqTrainer/beam、ZeroGR树、Recommenders SAR、sklearn TF-IDF/归一化、SQLite FTS5 BM25、arxiv.py解析、smolagents循环及FastAPI。版本、许可、维护/风险与适配成本在[第三方记录](../THIRD_PARTY_NOTICES.md)和各阶段upstream-audit.json。没有自建这些算法/框架。

本项目承担ID与目标适配、统一时点/seen、冷论文分支支持门控、匹配消融和完整分母评测、无损过滤、来源/会话预算、schema实例所有权修复及失败审计。本轮是现有材料的离线整理和接口薄包装，复用已有调研/封存组件，不启动新算法或依赖选型。
'''


def main() -> None:
    target=REPORT/'evidence-index.json';doc=Path('docs/ALGORITHM_EVIDENCE_2026.md')
    if target.exists() or doc.exists():raise ValueError('Preserve completed evidence bundle')
    evidence=collect();save(target,evidence);doc.write_text(markdown(evidence),encoding='utf-8')
    print(json.dumps({'claims':len(evidence['claims']),'document':str(doc)}))


if __name__=='__main__':main()
