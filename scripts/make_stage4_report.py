"""Render source-linked retrieval results and paired, query-level uncertainty."""
import json
from pathlib import Path

import numpy as np

from gsearch.benchmark_identifiers import METHODS, state, training_state
from gsearch.identifiers import sha256


ROOT = Path("reports/stage4")
NAMES = {"bm25": "BM25", "numeric": "数字ID T5", "title": "标题ID T5", "title_rrf": "BM25＋标题ID RRF"}


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def paired(first: dict, second: dict) -> dict:
    a, b = first["queries"], second["queries"]
    if not a or len(a) != len(b) or any((x["claim_id"], x["query"], x["relevant"]) !=
                                        (y["claim_id"], y["query"], y["relevant"]) for x, y in zip(a, b)):
        raise ValueError("Paired results must have identical query IDs, order and judgments")
    rng = np.random.default_rng(20261025)
    indices = rng.integers(0, len(a), size=(10000, len(a)))
    result = {}
    for name in ("recall", "mrr", "ndcg"):
        delta = np.array([x[name] - y[name] for x, y in zip(a, b)])
        bootstrap = delta[indices].mean(axis=1)
        result[name] = {"mean_delta": float(delta.mean()),
                        "bootstrap_95_percentile_interval": np.quantile(bootstrap, [0.025, 0.975]).tolist(),
                        "wins": int((delta > 1e-12).sum()), "losses": int((delta < -1e-12).sum()),
                        "ties": int((abs(delta) <= 1e-12).sum())}
    result["resampling"] = "10000 paired query resamples, seed20261025; descriptive, single training seed"
    result["queries"] = [{"claim_id": x["claim_id"], "query": x["query"],
                          "recall_delta": x["recall"] - y["recall"],
                          "mrr_delta": x["mrr"] - y["mrr"]} for x, y in zip(a, b)]
    return result


def main() -> None:
    plan = read(ROOT / "plan.json")
    lock = read(ROOT / "locked-before-dev.json")
    if state() != plan["state"] or training_state() != lock["weights"] or sha256(ROOT / "plan.json") != lock["plan_sha256"]:
        raise ValueError("Frozen assets changed")
    data = {split: {m: read(ROOT / f"{m}-{split}.json") for m in METHODS} for split in ("tuning", "dev")}
    for split in data:
        expected = 46 if split == "tuning" else 188
        for m, report in data[split].items():
            if report["summary"]["judged_queries"] != expected or report["k"] != 10:
                raise ValueError("Incomplete evaluation")
            paired(report, data[split]["bm25"])
    comparisons = {f"{a}-minus-{b}": paired(data["dev"][a], data["dev"][b]) for a, b in (
        ("title", "numeric"), ("title", "bm25"), ("title_rrf", "bm25"))}
    Path("reports/stage4-paired.json").write_text(json.dumps(comparisons, indent=2, ensure_ascii=False), encoding="utf-8")
    table = []
    for split in ("tuning", "dev"):
        for method, report in data[split].items():
            s = report["summary"]
            table.append(f"| {split} | {NAMES[method]} | {s['judged_queries']} | {s['recall@10']:.4f} | "
                         f"{s['mrr@10']:.4f} | {s['ndcg@10']:.4f} | {s['mean_seconds']*1000:.2f} |")
    pairs = []
    for label, comparison in comparisons.items():
        for metric in ("recall", "mrr", "ndcg"):
            row = comparison[metric]
            lo, hi = row["bootstrap_95_percentile_interval"]
            pairs.append(f"| {label} | {metric}@10 | {row['mean_delta']:+.4f} | [{lo:+.4f}, {hi:+.4f}] | "
                         f"{row['wins']}/{row['losses']}/{row['ties']} |")
    audit = read(Path("data/stage4-title/identifier-audit.json"))
    numeric = read(Path("runs/t5-dsi-4000-seed42/run.json"))
    title = read(Path("runs/t5-title12-4000-seed42/run.json"))
    budget = []
    for name, run in (("numeric", numeric), ("title", title)):
        receipt = audit["training_receipts"][name]
        budget.append(f"| {NAMES[name]} | {receipt['catalog_target_tokens']['mean']:.3f} | {receipt['input_tokens']} | "
                      f"{receipt['label_tokens']} | {receipt['padded_label_tokens']} | {run['seconds']:.2f} | "
                      f"{run['peak_allocated_mib']:.2f} |")
    examples = []
    differences = comparisons["title-minus-numeric"]["queries"]
    for tag, predicate in (("提高", lambda x: x > 1e-12), ("下降", lambda x: x < -1e-12)):
        chosen = sorted((r for r in differences if predicate(r["recall_delta"])), key=lambda r: int(r["claim_id"]))[:3]
        for row in chosen:
            examples.append(f"| {tag} | {row['claim_id']} | {row['recall_delta']:+.3f} | {row['query'].replace('|', '/')} |")
    delta = comparisons["title-minus-numeric"]["recall"]["mean_delta"]
    supervised_docs = {d for c in read(Path("data/prepared/train.json")) for d in c["evidence"]}
    groups = []
    for method, result in data["dev"].items():
        for all_seen in (True, False):
            rows = [q for q in result["queries"] if set(q["relevant"]).issubset(supervised_docs) == all_seen]
            label = "全部gold文档曾有train查询监督" if all_seen else "至少一篇gold文档无train查询监督"
            groups.append(f"| {NAMES[method]} | {label} | {len(rows)} | "
                          f"{sum(r['recall'] for r in rows)/len(rows):.4f} | "
                          f"{sum(r['mrr'] for r in rows)/len(rows):.4f} |")
    doc = f'''# 第四阶段：标题前缀文档ID与生成式检索

本轮实际训练一个新的T5-small，以标题前缀ID替换纯数字ID。完整公开dev188条带证据查询上，Recall@10相对数字ID变化 **{delta:+.4f}**。所有预定方法和完整失败均纳入；算法优势应同时看排序指标、BM25参照与成本，不能从单一指标推断事实核验或Agent收益。

## 改了什么

静态5183篇文档各取标题前12个非special的T5子词，接 ` | 原数字码`；规范化后检查encode/decode稳定、一一对应和完整合法trie路径。重复标题仍由数字后缀区分，空/未知字符标题回退document前缀。它是规则构造的文本DocID，不是学习得到的语义码本。原doc_id、标题、摘要和三个claim文件保持相同；训练目标与解码目录改变，旧Agent与核验器继续使用原配置。

名称生成检索思路参考[GENRE原论文](https://arxiv.org/abs/2010.00904)。官方[仓库](https://github.com/facebookresearch/GENRE)已归档，根[LICENSE](https://github.com/facebookresearch/GENRE/blob/main/LICENSE)为CC BY-NC4.0；本轮没有导入其代码、权重或数据，继续复用现有Transformers T5训练/beam和项目trie，见[来源说明](../THIRD_PARTY_NOTICES.md)。这是小目录适配实验，不是原论文复现或新提出的方法。

## 训练与协议

两种T5均从同一固定revision基础权重开始，全参数训练4000步、batch8、seed42、lr0.0005、max input160、query fraction0.5，AdamW及BF16设置不变。标题模型只读train727条的503个query-doc对以及静态目录内容；没有用tuning/dev标签更新梯度。静态目录包含dev相关文档，属于闭集检索。

抽样顺序hash一致，均index15991次/query16009次；输入token相同。数字模型复用第一阶段已经训练的检查点，标题模型重新训练；两者步数与样本曝光相同，标签长度和实际计算量不同。

| 模型 | 平均DocID token含EOS | 有效输入token | 有效标签token | padding后标签token | 训练秒 | 峰值allocated MiB |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(budget)}

token预算由完全相同的随机采样器离线重放计数，不是GPU FLOPs测量。旧数字训练当时与早期调试存在部分重叠，墙钟不作为吞吐对照；allocated不等于整机显存。不同ID长度也改变损失归一化与解码路径，缺少等长无语义前缀对照，不能把差异全部归因于语义信息。

[训练前协议](stage4/plan.json)在标题训练前固定12子词、4000步、seed42、beam10、K10与四方法；本轮没有按tuning选择超参数或checkpoint。完成tuning后，[权重/代码冻结](stage4/locked-before-dev.json)记录全部输出hash，再运行dev。RRF预先指定等权、常数60、每路Top10。训练日志见[train-title.log](stage4/train-title.log)。

## 检索结果

| split | 方法 | 有相关标注查询 | Recall@10 | MRR@10 | NDCG@10 | 平均毫秒 |
|---|---|---:|---:|---:|---:|---:|
{chr(10).join(table)}

标题ID相对数字ID的Recall更高，但相对BM25仍有明显差距；其平均解码延迟也更高。标题RRF相对BM25的Recall只提高约0.38个百分点，MRR和NDCG反而下降，因此不据此替换现有参照或宣称整体胜出。旧Agent检索配置保持原样。

每种方法均完整运行同一split；tuning80条中34条、dev300条中112条无证据标注，不参加Recall/MRR/NDCG分母，未硬算0。指标沿用第一阶段实现；未标注证据完整性仍有限。没有更改阈值、核验模型或Agent策略，也未测下游事实核验的变化。

计时batch1，排除各方法一次预热，包含分词/生成/查表；方法顺序固定BM25→数字→标题→标题RRF，本项目没有并行训练或运行Agent。这里是单次本机记录，不是随机顺序的正式性能基准。每查询预测和生成的文本ID见[BM25 dev](stage4/bm25-dev.json)、[数字ID dev](stage4/numeric-dev.json)、[标题ID dev](stage4/title-dev.json)、[标题RRF dev](stage4/title_rrf-dev.json)。

## 相同查询的配对差异

| 对比（前者减后者） | 指标 | 平均差 | 描述性95%区间 | 提高/下降/相同查询数 |
|---|---|---:|---|---|
{chr(10).join(pairs)}

对同一188条query进行10000次有放回配对bootstrap，seed20261025。区间只反映这批查询的重采样变化，不含训练随机性；共享文献的query未按文献聚类，不能当独立重复实验或多种子显著性证明。完整逐查询差异见[配对结果](stage4-paired.json)。公开dev已用于前三阶段，因此这些是复用dev的描述性比较，不能称为未见独立测试。

## 查询监督覆盖诊断

| 方法 | 分组 | query数 | Recall@10 | MRR@10 |
|---|---|---:|---:|---:|
{chr(10).join(groups)}

分组仅看相关文档是否曾在train查询标注中出现；后一组可能也有其他gold文档接受过监督。所有文档内容仍参与索引训练，因此此表不是未见新文档测试，也不用于选模型。

生成模型的失败集中在缺少相关文档查询监督的组：数字ID的Recall约0.6%，标题ID约11.9%，BM25约94.3%。这说明当前索引训练还不能替代足够的检索查询覆盖；它是下一轮查询增强实验的依据，不能据此断言唯一原因或预先保证收益。

## 改善与退化案例

以下分别按ID取前三条Recall提高和下降查询，用于诊断，不根据这些案例选模型；完整结果保留所有query。

| 方向 | claim ID | Recall差 | 原始查询 |
|---|---|---:|---|
{chr(10).join(examples)}

## 复现与验证

完整的准备→训练→tuning→冻结→dev命令见[README](../README.md)。本机权重已准备，可只重评到一个新文件：

```powershell
& $py -m gsearch.evaluate --data data/stage4-title --split dev --retriever dsi --checkpoint runs/t5-title12-4000-seed42 --beam 10 --k 10 --output reports/title-repeat-dev.json
& $py -m scripts.make_stage4_report
```

[测试日志](stage4/tests.log)记录36项测试通过，覆盖已有工具预算和证据隔离，以及文本ID重复标题/未知字符、完整trie解码、配对查询错位拒绝与冻结漂移。全目录映射另与实际构造器核对，模型/数据/代码hash在评估前和报告前复核。原阶段3冻结代码未改变。

本轮只有一个训练种子、一种标题长度和固定闭集科学摘要目录；没有自然多跳、新文档、中文或线上用户验证。可读ID、合法解码或更高检索指标均不保证引用立场正确。下一项算法决策应以生成模型相对强BM25的质量/成本差距为依据，不默认新增Agent轮次会改善。
'''
    target = Path("reports/阶段4_标题ID生成检索.md")
    target.write_text(doc, encoding="utf-8")
    print(json.dumps({"report": str(target), "title_minus_numeric_recall": delta,
                      "dev": {m: r["summary"] for m, r in data["dev"].items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
