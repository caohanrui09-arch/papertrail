"""Summarize matched continuations without attributing extra steps to QG."""
from collections import defaultdict
import json
from pathlib import Path

from gsearch.benchmark_query_aug import METHODS, RUNS, check_state, trained_models
from gsearch.identifiers import sha256
from gsearch.query_augmentation import normalize
from scripts.make_stage4_report import paired


ROOT = Path("reports/stage5")
NAMES = {"bm25": "BM25", "title4000": "标题ID4000步", "control8000": "原索引继续训练8000步",
         "qg8000": "生成查询继续训练8000步", "qg_rrf": "BM25＋生成查询RRF"}


def read(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    plan, lock = read(ROOT / "plan.json"), read(ROOT / "locked-before-dev.json")
    check_state(plan)
    if trained_models(plan) != lock["models"] or sha256(ROOT / "plan.json") != lock["plan_sha256"]:
        raise ValueError("Models changed after dev freeze")
    if {m: sha256(ROOT / f"{m}-tuning.json") for m in METHODS} != lock["tuning"]:
        raise ValueError("Tuning outputs changed")
    data = {split: {m: read(ROOT / f"{m}-{split}.json") for m in METHODS} for split in ("tuning", "dev")}
    for split in data:
        for report in data[split].values():
            if report["summary"]["judged_queries"] != (46 if split == "tuning" else 188):
                raise ValueError("Incomplete evaluation")
            paired(report, data[split]["bm25"])
    comparisons = {f"{a}-minus-{b}": paired(data["dev"][a], data["dev"][b]) for a, b in (
        ("qg8000", "control8000"), ("control8000", "title4000"),
        ("qg8000", "title4000"), ("qg8000", "bm25"), ("qg_rrf", "bm25"))}
    Path("reports/stage5-paired.json").write_text(json.dumps(comparisons, ensure_ascii=False, indent=2), encoding="utf-8")
    table = []
    for split, reports in data.items():
        for method, result in reports.items():
            s = result["summary"]
            table.append(f"| {split} | {NAMES[method]} | {s['judged_queries']} | {s['recall@10']:.4f} | "
                         f"{s['mrr@10']:.4f} | {s['ndcg@10']:.4f} | {s['mean_seconds']*1000:.2f} |")
    pair_table = []
    for label, result in comparisons.items():
        for metric in ("recall", "mrr", "ndcg"):
            r = result[metric]
            lo, hi = r["bootstrap_95_percentile_interval"]
            pair_table.append(f"| {label} | {metric}@10 | {r['mean_delta']:+.4f} | [{lo:+.4f},{hi:+.4f}] | "
                              f"{r['wins']}/{r['losses']}/{r['ties']} |")
    supervised = {d for c in read(Path("data/stage4-title/train.json")) for d in c["evidence"]}
    group_table, group_scores = [], {}
    for method, result in data["dev"].items():
        group_scores[method] = {}
        for all_seen in (True, False):
            rows = [q for q in result["queries"] if set(q["relevant"]).issubset(supervised) == all_seen]
            label = "全部gold文档有原train查询监督" if all_seen else "至少一篇gold文档无原train查询监督"
            recall = sum(q["recall"] for q in rows)/len(rows)
            group_scores[method][str(all_seen)] = {"queries": len(rows), "recall": recall}
            group_table.append(f"| {NAMES[method]} | {label} | {len(rows)} | {recall:.4f} | "
                               f"{sum(q['mrr'] for q in rows)/len(rows):.4f} |")
    runs = {mode: read(folder / "run.json") for mode, folder in RUNS.items()}
    budget = []
    for mode, run in runs.items():
        u, e = run["usage"], run["exposures"]
        budget.append(f"| {mode} | {e['gold_query']} | {e['index']} | {e['synthetic_query']} | "
                      f"{u['input_tokens']} | {u['padded_input_tokens']} | {u['label_tokens']} | "
                      f"{u['padded_label_tokens']} | {run['corpus_documents_sampled']} | {run['seconds']:.2f} | "
                      f"{run['peak_allocated_mib']:.2f} |")
    audit = read(Path("data/stage5-queries/audit.json"))
    queries = read(Path("data/stage5-queries/queries.json"))
    texts = defaultdict(set)
    for r in queries:
        for q in r["queries"]:
            texts[normalize(q)].add(r["doc_id"])
    exposed_weak_pairs = sum(min(len(r["queries"]), runs["qg"]["per_document_visits"][r["doc_id"]]) for r in queries)
    examples = [f"| {r['doc_id']} | {' / '.join(r['raw_candidates']).replace('|','/')} |" for r in queries[:3]]
    overlap = read(ROOT / "overlap-audit.json")
    qg = data["dev"]["qg8000"]["summary"]
    control = data["dev"]["control8000"]["summary"]
    bm25 = data["dev"]["bm25"]["summary"]
    main_effect = comparisons["qg8000-minus-control8000"]["recall"]
    report = f'''# 第五阶段：生成查询弱监督与同预算继续训练

真实doc2query生成、两个独立继续训练分支和完整tuning/dev评估均已完成。主对照是**同样继续训练4000步的qg与control**：dev Recall@10分别为 **{qg['recall@10']:.4f}/{control['recall@10']:.4f}**，差 **{main_effect['mean_delta']:+.4f}**。BM25为 **{bm25['recall@10']:.4f}**。不把相对旧4000步模型的全部差异归给查询增强，也不预设它应优于BM25。

本轮没有测出稳定的查询增强收益：主比较只有2条query的Recall提高、1条下降、185条相同，描述性区间跨0；增强分支Recall还低于旧4000步标题模型。现有模型和Agent配置保持原样。这项结论限于当前通用教师、每篇2候选和4000步继续训练设置。

## 数据与方法

检索模型继续使用阶段4的T5-small和标题前12子词＋数字后缀DocID，静态5183篇文档、727/80/300原始claim划分不变。原阶段2/3核验和Agent配置不改，本轮没有测下游事实核验或Agent质量。

冻结的[doc2query教师模型](https://huggingface.co/doc2query/msmarco-t5-small-v1)基于T5-v1_1-small，模型卡记录MSMARCO500k查询-段落对训练，Apache-2.0，revision `eb04306040c87ff35caa4c87078dfd94a6b7b64e`。原bin发布哈希校验、纯张量读取和本地safetensors转换见[来源说明](../THIRD_PARTY_NOTICES.md)与[下载记录](stage5/download-teacher.log)。没有导入其训练脚本、优化器或SciFact适配权重；不能独立排除基础预训练文本交集。

生成器只打开静态documents文件，输入标题＋摘要，截断320token。每文档采样2个候选，top_p0.95/top_k0、max new tokens64、batch16、逐batch seed20261025+offset；原始候选原样保存，只去掉空文本和同文档内规范化完全重复。没有按gold、重排分数或检索成败清洗。

共 **{audit['raw_candidates']}** 原始候选、**{audit['accepted_queries']}** 保留查询，覆盖 **{audit['documents']}** 篇文档，回退 **{audit['fallback_documents']}** 篇。全局唯一规范化文本 **{len(texts)}**，其中 **{sum(len(ds)>1 for ds in texts.values())}** 个文本链接到多篇文档。弱查询的源文档关联不是经过核验的相关性或立场标注。

批内generate＋解码累计 **{audit['generation_seconds']:.2f}秒**（不含教师载入、分词与文件写入），教师峰值allocated **{audit['peak_allocated_mib']:.2f}MiB**。这部分成本只属于qg路线，不能隐去；教师不在在线查询路径上。输入与原始输出、逐批token成本/哈希记录在 `data/stage5-queries/`。

思路参考[DSI-QG官方实现](https://github.com/ArvinZhuang/DSI-QG)：用生成查询表示文档以缩小索引/检索输入差异。我们复用现有Transformers loss/generation/beam及本地训练适配；原实现的8V100、大教师、多查询规模未复现。这里仅是固定小预算实验。

## 匹配继续训练预算

两个分支从**同一个阶段4标题ID4000步检查点**开始，各继续4000步，累计8000梯度步。均重置相同AdamW，lr0.0005、weight decay0.01、clip1.0、batch8、seed42、max input160、相同BF16设置。不恢复旧优化器。

50%抽样仍使用原始train查询→DocID；其余50%抽样文档时，control使用 `index: 标题+摘要`，qg使用 `search: 教师查询`，同一文档的候选按访问次数轮换。task/doc随机序列、每步所有目标DocID、原始查询曝光完全配对；标签token数量也相同。改变的是这一半输入的内容和任务前缀，不是DocID或模型参数量。

| 分支 | 原train查询曝光 | 原索引曝光 | 弱查询曝光 | 有效输入token | padded输入token | 有效标签token | padded标签token | 实际抽到的文档数 | 继续训练秒 | 峰值allocated MiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(budget)}

生成覆盖整个目录，随机继续训练并非每篇必定抽到，表中单列实际覆盖；按访问次数与候选轮换重放，实际使用的不同弱查询-文档对为 **{exposed_weak_pairs}**。两个分支相同步数、标签和抽样，不代表相同输入token或GPU计算量。训练来自同一既有检查点，仍只有一个种子；成本不能作为普遍吞吐结论。allocated是本进程张量峰值，不等于整机显存。

[训练前协议](stage5/plan.json)在两个继续训练分支启动前冻结代码、数据和初始权重。完整tuning完成后，[dev前锁定](stage5/locked-before-dev.json)冻结所有模型权重、tokenizer/config、run及tuning输出hash，再运行dev。没有按tuning选择比例、候选清洗、学习率、步数或RRF权重。

## 完整检索结果

| split | 方法 | 有相关标注query | Recall@10 | MRR@10 | NDCG@10 | 平均毫秒 |
|---|---|---:|---:|---:|---:|---:|
{chr(10).join(table)}

每种方法均运行整个同一split，tuning34条/dev112条无证据标注query单列排除于排序指标分母。不能把无标注当已证明无相关文档。RRF预先固定两路Top10、等权、常数60。batch1单次本机计时排除预热，包含分词/生成/查表；本项目没有并行训练或运行Agent，固定顺序且未做随机化性能基准。

## 配对差异

| 前者减后者 | 指标 | 平均差 | 描述性95%区间 | 提高/下降/相同 |
|---|---|---:|---|---|
{chr(10).join(pair_table)}

同188条query、10000次配对bootstrap、seed20261025；区间只表示这批query重采样，不包含训练随机性，也未按共享文档聚类。主比较是qg8000-control8000；旧4000步参照用于分开观察额外训练影响。所有逐query差异见[配对记录](stage5-paired.json)。公开dev在历史阶段已使用，因此本轮是描述性比较，不称独立测试或多种子证据。

## 原始查询监督覆盖组

| 方法 | 分组 | query数 | Recall@10 | MRR@10 |
|---|---|---:|---:|---:|
{chr(10).join(group_table)}

分组固定依据原train的人工查询文档标注，未把新增伪查询算作原监督；后一组可能还包含接受过原监督的其他gold文档。所有文档内容本就参与过索引学习，不是新文档测试。组间差异不能解释为唯一因果机制。

原监督缺少组的Recall为qg10.80%、control9.66%，旧4000步模型为11.93%；当前增强未修复上一阶段的覆盖瓶颈。全体query上，RRF相对BM25仅增加约0.56个百分点Recall，MRR下降约4.83个百分点，因此不据此宣称整体效果胜出。通用搜索问句和科学论断之间的分布差异、弱标签质量及训练不足仍是待验证解释，不能从这一次实验确定唯一原因。

## 查询质量与重叠

以下直接展示目录顺序最前3篇的原始候选，没有选最好例子。可能有拼写、事实关联和科学论断/搜索问句分布差异，训练前没有通过gold挑选。

| 来源doc ID | 原始两候选 |
|---|---|
{chr(10).join(examples)}

两个模型冻结后才进行规范化完全相等审计：[完整记录](stage5/overlap-audit.json)。合成文本与原train/tuning/dev查询完全相等的条数分别 **{overlap['splits']['train']['exact_normalized_matches']}/{overlap['splits']['tuning']['exact_normalized_matches']}/{overlap['splits']['dev']['exact_normalized_matches']}**；未据此过滤或重训。精确匹配审计不排除语义近似或预训练交集。静态目录包含dev相关文档，属于闭集索引方案。

## 复现与检查

命令顺序见[README](../README.md)，训练日志见[control](stage5/train-control.log)、[qg](stage5/train-qg.log)，原始评价见[BM25](stage5/bm25-dev.json)、[旧模型](stage5/title4000-dev.json)、[control](stage5/control8000-dev.json)、[qg](stage5/qg8000-dev.json)、[RRF](stage5/qg_rrf-dev.json)。

[测试记录](stage5/tests.log)记录40项测试通过，覆盖候选去重/回退、拒绝不完整目录、严格配对目标和原始查询，以及既有引用隔离、预算与解码检查。原始预测重新计分并核对冻结资产。低质量弱标签、所有回退和完整轨迹保留，结果包括全部query。

本轮未改Agent策略、证据核验阈值或部署默认配置，也没有测中文、新文档或线上效果；结果只能支持当前闭集科学摘要任务的算法诊断。
'''
    path = Path("reports/阶段5_生成查询增强对照.md")
    path.write_text(report, encoding="utf-8")
    print(json.dumps({"report": str(path), "main_recall_effect": main_effect,
                      "dev": {m: r["summary"] for m, r in data["dev"].items()},
                      "group_scores": group_scores}, ensure_ascii=False))


if __name__ == "__main__":
    main()
