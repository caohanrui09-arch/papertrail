"""Report frozen-model prefix/beam changes with cost and legacy equivalence."""
import json
from pathlib import Path

from gsearch.benchmark_prefix import METHODS, ROOT, check_state, legacy_equivalence
from gsearch.identifiers import sha256
from scripts.make_stage4_report import paired


def read(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    plan, lock = read(ROOT / "plan.json"), read(ROOT / "locked-before-dev.json")
    check_state(plan)
    legacy_equivalence()
    if (lock["plan_sha256"] != sha256(ROOT / "plan.json") or
            lock["tuning"] != {m: sha256(ROOT / f"{m}-tuning.json") for m in (*METHODS, "bm25")} or
            lock["indexes"] != {n: sha256(ROOT / f"{n}-index.json") for n in ("full", "short")}):
        raise ValueError("Frozen selection inputs differ")
    data = {s: {m: read(ROOT / f"{m}-{s}.json") for m in (*METHODS, "bm25")} for s in ("tuning", "dev")}
    for split, methods in data.items():
        for result in methods.values():
            if result["summary"]["judged_queries"] != (46 if split == "tuning" else 188):
                raise ValueError("Incomplete evaluation")
            paired(result, methods["full_b10"])
    selected = lock["selected"]
    comparisons = {label: {"first": a, "second": b, **paired(data["dev"][a], data["dev"][b])}
                   for label,a,b in (("full50-minus-full10", "full_b50", "full_b10"),
                                     ("short10-minus-full10", "short_b10", "full_b10"),
                                     ("short50-minus-full50", "short_b50", "full_b50"))}
    Path("reports/stage7-paired.json").write_text(json.dumps(comparisons,indent=2,ensure_ascii=False),encoding="utf-8")
    table=[]
    for split, methods in data.items():
        for method,r in methods.items():
            s=r["summary"]
            table.append(f"| {split} | {method} | {s['recall@10']:.4f} | {s['mrr@10']:.4f} | "
                         f"{s['ndcg@10']:.4f} | {s['mean_seconds']*1000:.2f} |")
    work=[]
    for method in METHODS:
        r=data["dev"][method];p=r["decode_work"]
        steps=sum(x["generation_steps"] for x in p)/len(p)
        slots=sum(x["beam_decoder_slots"] for x in p)/len(p)
        returned=[t for x in p for t in x["returned_alias_tokens_including_eos"]]
        work.append(f"| {method} | {r['beam']} | {steps:.2f} | {slots:.2f} | {sum(returned)/len(returned):.2f} | "
                    f"{r['summary']['mean_seconds']*1000:.2f} |")
    pairs=[]
    for label,result in comparisons.items():
        for metric in ("recall","mrr","ndcg"):
            r=result[metric];lo,hi=r["bootstrap_95_percentile_interval"]
            pairs.append(f"| {label} | {metric}@10 | {r['mean_delta']:+.4f} | [{lo:+.4f},{hi:+.4f}] | "
                         f"{r['wins']}/{r['losses']}/{r['ties']} |")
    train=read(Path("data/stage4-title/train.json"))
    supervised={d for c in train for d in c["evidence"]}
    groups=[]
    for method in (*METHODS,"bm25"):
        for all_seen in (True,False):
            rows=[q for q in data["dev"][method]["queries"] if set(q["relevant"]).issubset(supervised)==all_seen]
            label="全部gold文档有原train查询监督" if all_seen else "至少一篇gold文档无原train查询监督"
            groups.append(f"| {method} | {label} | {len(rows)} | {sum(q['recall'] for q in rows)/len(rows):.4f} | "
                          f"{sum(q['mrr'] for q in rows)/len(rows):.4f} |")
    full=read(ROOT/"full-index.json")["stats"];short=read(ROOT/"short-index.json")["stats"]
    alignment=read(ROOT/"target-alignment-audit.json")
    score_diag=read(ROOT/"beam-score-diagnostic.json")
    old=data['dev']['full_b10']['summary'];chosen=data['dev'][selected]['summary']
    report=f'''# 第七阶段：T5直接生成ID的前缀树与beam对照

本轮没有增加训练步数或更换模型。先比较ZeroGR、GenRet、Tevatron，再实际复用Apache-2.0的ZeroGR前缀树组件。tuning选择 **{selected}**；dev188条带证据查询上，其Recall/MRR/NDCG@10为 **{chosen['recall@10']:.4f}/{chosen['mrr@10']:.4f}/{chosen['ndcg@10']:.4f}**，原完整树beam10为 **{old['recall@10']:.4f}/{old['mrr@10']:.4f}/{old['ndcg@10']:.4f}**。所有四个条件与BM25强参照完整保留。

## 开源来源与实际复用

[选型记录](阶段7_开源解码方案对比.md)先于本轮结果形成。[ZeroGR](https://github.com/sunnweiwei/ZeroGR/tree/0fb7f4ebfc446e5c8a2389f3f55bbe245877408d)的newTree类体原样提取，原genir.py全文作为非导入文本保存，Git blob与AST均核验；完整Apache-2.0许可与上游README保留。仅加载[独立树模块](../third_party/zerogr_prefix/tree.py)，不执行其主训练/评估、kill_gpu.sh、pickle或自动模型下载路径。

本项目[适配](../gsearch/prefix_decoder.py)只处理索引覆盖、T5解码器起点/EOS、真实token路径到原doc_id的映射及日志。模型加载、tokenization与beam search由现有Transformers负责，未自己实现搜索引擎或训练循环；GenRet/Tevatron源码没有导入。上游硬件/模型/数据规模及完整ZeroGR方法没有复现。

## 索引结构与模型边界

固定阶段4标题ID T5-small4000步检查点、完整5183篇目录与原始查询划分。压缩只读取原始DocID token字符串，将它缩成唯一前缀＋EOS；每篇恰好保留一个可还原别名。没有用holdout查询/标签选择前缀。原文摘要、句子编号和核验/Agent配置未改。

| 索引 | 文档/唯一别名数 | 实际树节点 | 平均token含EOS | 最短/最长token |
|---|---:|---:|---:|---|
| 完整 | {full['documents']} | {full['actual_tree_nodes']} | {full['mean_tokens_including_eos']:.3f} | {full['min_tokens']}/{full['max_tokens']} |
| 压缩 | {short['documents']} | {short['actual_tree_nodes']} | {short['mean_tokens_including_eos']:.3f} | {short['min_tokens']}/{short['max_tokens']} |

完整[别名与映射](stage7/short-index.json)逐篇检查覆盖、唯一性、原ID前缀及EOS。原类build包含宽泛异常捕获，因此没有只信构建返回值。运行结束后仍校验10条结果全部合法、唯一和完整。

**模型仍针对旧完整ID训练。** 压缩改变EOS位置与用于length penalty的序列长度，不能把它当成无需对齐的等价目标，也不能把所有差异归因于搜索宽度。目录平均路径变短只是静态结构统计，不等于生成更准或按比例提速。

无标签的[目标审计](stage7/target-alignment-audit.json)显示，{alignment['eos_position_changed']}/{alignment['documents']}篇的EOS位置发生变化；另有{alignment['text_roundtrip_changed']}个token别名在decode为文本后重新encode会变化。因此本适配器始终按**原始token路径**查找文档，不通过显示字符串重分词来还原。审计不用于改选前缀或训练。

## 固定2×2协议

full/short × beam10/50均返回10篇，使用HF原生generate、do_sample=False、length_penalty1、renormalize_logits=False。beam50增加搜索工作量，同K不是同计算预算。先在[协议](stage7/plan.json)固定模型/代码/数据/候选，再完整运行tuning。

full_b10在全部46条带证据tuning上与阶段4的完整Top10逐项一致，证明新适配器的原方法参照没有换排名。之后按tuning NDCG→MRR→Recall、较小beam、完整树选型，锁定 **{selected}**；[dev前锁定](stage7/locked-before-dev.json)绑定全部tuning与索引hash，再完整运行dev。BM25是强参照，不参与T5解码选型。

## 检索结果

| split | 条件 | Recall@10 | MRR@10 | NDCG@10 | 平均毫秒 |
|---|---|---:|---:|---:|---:|
{chr(10).join(table)}

tuning选择完整树beam50，但它在本轮dev没有超过旧beam10；短树的检索质量也明显退化。候选未通过这批dev验证，原默认配置保持不变。没有在dev上重新选择或重新调参后报告同一批结果。

tuning80条中46条、dev300条中188条有相关文档标注并进入排序指标，另34/112条不强行算零。全部方案使用相同原始claim、gold相关文档集合与指标实现。公开dev多次使用，本轮只有一个冻结模型，因此仅作描述性评价。

## 实际解码工作量

| 条件 | beam | 平均生成步数 | 平均beam×steps槽位 | 返回别名平均token含EOS | 平均毫秒 |
|---|---:|---:|---:|---:|---:|
{chr(10).join(work)}

工作槽位只是HF beam矩形前向行数的代理，含结束流的占位，不是GPU FLOPs。编码器input token、每查询步数与全部返回token长度保存在raw结果的decode_work中，排除各条件首个warmup。返回序列变短与批量beam何时停止不同，不能只用平均目录长度推断计算量。

本机batch1、包含分词/原生生成/上游callback/查表，方法顺序固定；没有并行本项目训练或Agent，但未做随机顺序性能基准。[单次GPU采样](stage7/device-sample.json)在dev full_b10时观察到P5、315MHz SM/810MHz显存时钟；它不是全程trace。当前延迟同时包含上游Python树回调和设备状态，**不与历史阶段速度直接作收益比值**。

## 同查询配对

| 前者减后者 | 指标 | 平均差 | 描述性95%区间 | 提高/下降/相同 |
|---|---|---:|---|---|
{chr(10).join(pairs)}

[逐查询记录](stage7-paired.json)使用10000次配对query bootstrap、seed20261025；区间只反映这批query重采样，不含模型训练种子差异，也未按共享文献聚类，不作独立实验或普遍显著性结论。

事后[beam分数诊断](stage7/beam-score-diagnostic.json)单列为post-hoc，未参与tuning选型或调参。在beam50相对beam10丢失的{score_diag['lost_judged_document_query_pairs']}个相关文档-query对中，{score_diag['wide_min_score_above_old_gold']}个对应的beam50末位返回分数仍高于旧相关文档分数（容差1e-4）。这与模型序列评分排序和公开相关标注不一致相符；未标注候选也可能包含漏标相关文献，不能把它们一律视为不相关。比较的是同一模型/完整树/查询/length penalty下的两个近似搜索结果，未穷举全目录，不能据此证明全局最优或唯一原因。

## 原始查询监督覆盖组

| 条件 | 分组 | query数 | Recall@10 | MRR@10 |
|---|---|---:|---:|---:|
{chr(10).join(groups)}

分组只依据原train的人工查询监督；后一组可能含其他曾有监督的gold文档。所有目录内容都参与过索引训练，不是新文档测试。较宽beam的改善和别名压缩的失败只支持本轮已测试的设置；不能代替对压缩目标进行匹配训练的独立对照。

## 验证与复现

[51项检查](stage7/tests.log)包含原class AST、全部别名合法路径、原doc_id/标题还原、非法/不完整/重复输出拒绝，以及既有引用、预算与数据隔离检查。模型真实小样本契约和整个tuning的历史完整排名等价验证已执行。全部raw预测、tuning选择与历史冻结资产另行重计分/核对；没有改旧实验文件。

完整命令见[README](../README.md)，源码与许可见[THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES.md)。本轮没有将压缩方案或较宽beam自动切换进原Agent，也不声称可靠科学事实核验能力或线上收益。
'''
    path=Path("reports/阶段7_前缀树解码对照.md")
    path.write_text(report,encoding="utf-8")
    print(json.dumps({"report":str(path),"selected":selected,
                      "dev":{m:r['summary'] for m,r in data['dev'].items()},
                      "full50_vs_full10":comparisons['full50-minus-full10']['recall']},ensure_ascii=False))


if __name__ == "__main__":
    main()
