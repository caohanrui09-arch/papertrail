"""Report an actual upstream Doc2Query-- run, including negative selection."""
import json
from pathlib import Path

from gsearch.benchmark_expansion import CANDIDATES, ROOT, check_state
from gsearch.identifiers import sha256
from scripts.make_stage4_report import paired


NAMES = {"bm25": "原BM25", "expand_all": "追加全部查询", "filter_p50": "50分位过滤",
         "filter_p70": "70分位过滤", "filter_p90": "90分位过滤"}


def read(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    plan, lock = read(ROOT / "plan.json"), read(ROOT / "locked-before-dev.json")
    check_state(plan)
    if (lock["plan_sha256"] != sha256(ROOT / "plan.json") or
            lock["scores_sha256"] != sha256(ROOT / "scored-queries.json") or
            lock["tuning"] != {n: sha256(ROOT / f"{n}-tuning.json") for n in CANDIDATES}):
        raise ValueError("Frozen selection inputs changed")
    data = {split: {n: read(ROOT / f"{n}-{split}.json") for n in CANDIDATES} for split in ("tuning", "dev")}
    for split, methods in data.items():
        for result in methods.values():
            if result["summary"]["judged_queries"] != (46 if split == "tuning" else 188):
                raise ValueError("Incomplete evaluation")
            paired(result, methods["bm25"])
    selected = lock["selected"]
    comparisons = {label: {"first": a, "second": b, **paired(data["dev"][a], data["dev"][b])}
                   for label, a, b in (("all-minus-base", "expand_all", "bm25"),
                                      ("p70-minus-all", "filter_p70", "expand_all"),
                                      ("selected-minus-base", selected, "bm25"))}
    Path("reports/stage6-paired.json").write_text(json.dumps(comparisons, ensure_ascii=False, indent=2), encoding="utf-8")
    results = []
    for split, methods in data.items():
        for name, result in methods.items():
            s = result["summary"]
            results.append(f"| {split} | {NAMES[name]} | {s['recall@10']:.4f} | {s['mrr@10']:.4f} | "
                           f"{s['ndcg@10']:.4f} | {s['mean_seconds']*1000:.2f} |")
    footprint = []
    for name, result in data["dev"].items():
        r = result["index"]
        threshold = "—" if result["threshold"] is None else f"{result['threshold']:.5f}"
        footprint.append(f"| {NAMES[name]} | {threshold} | {r['appended_queries']} | {r['documents_with_expansion']} | "
                         f"{r['sqlite_nonfree_bytes']/2**20:.3f} | {r['sqlite_allocated_bytes']/2**20:.3f} | "
                         f"{r['build_seconds']:.2f} |")
    pair_table = []
    for label, comp in comparisons.items():
        for metric in ("recall", "mrr", "ndcg"):
            r = comp[metric];lo, hi = r["bootstrap_95_percentile_interval"]
            pair_table.append(f"| {label} | {metric}@10 | {r['mean_delta']:+.4f} | [{lo:+.4f},{hi:+.4f}] | "
                              f"{r['wins']}/{r['losses']}/{r['ties']} |")
    score = read(ROOT / "source-scoring-audit.json")
    selected_s = data["dev"][selected]["summary"]
    decision = ("tuning未选中扩展配置，按冻结选择保留原BM25。" if selected == "bm25" else
                f"tuning选中{NAMES[selected]}，其dev结果仅作本轮描述性评价；原Agent默认配置未切换。")
    report = f'''# 第六阶段：直接复用Doc2Query−−做文档扩展对照

已完成GitHub四方案对比、真实上游组件复用和完整tuning/dev对照。{decision}冻结选择在188条带相关标注的dev查询上，Recall/MRR/NDCG@10为 **{selected_s['recall@10']:.4f}/{selected_s['mrr@10']:.4f}/{selected_s['ndcg@10']:.4f}**。

本轮验证的是**生成查询扩展BM25索引**，没有训练或修改T5，也不把结果归为T5直接生成文档ID的提升。源码选型依据先于本轮结果，见[开源方案对比](阶段6_开源方案对比.md)。用户要求的“较大方案先查GitHub、比较许可和成本、优先复用”已记录在[AGENTS.md](../AGENTS.md)。

## 实际复用与适配

[PyTerrier Doc2Query−−](https://github.com/terrierteam/pyterrier_doc2query/tree/cf54da18a3bb4df2e11c18846241838771e4ecf5)的8份源码/元数据/许可证文件原样保留，MIT copyright2023 Sean MacAvaney完整保留。运行时逐文件检查Git blob，并实际调用原版 **QueryScorer、QueryFilter**；没有另外实现过滤选择器或用占位框架代替。上游源代码、固定commit和blob见[审计](stage6/upstream-audit.json)与[本地源码](../third_party/pyterrier_doc2query_upstream/pyterrier_doc2query/filtering.py)。

[本项目适配器](../gsearch/open_source_expansion.py)只转换数据接口，将已有冻结MiniLM的logits提供给上游scorer，再把选定查询追加至已有SQLite FTS5索引。PyTerrier1.1.2、alpha0.16.5及依赖置于独立环境，借用原共享CUDA包；原共享venv未安装/升级这些依赖。[安装记录](stage6/install-receipt.json)、[完整版本](../requirements-stage6-lock.txt)可复核。

实际契约测试与评分记录均显示JVM未启动。未调用上游Artefact.from_repo、Java索引或远程模型下载。与GLEN/NCI/SEAL的许可、维护、源码和迁移成本交叉对比见选型报告；没有复制未确认许可的NCI源码。

## 输入、过滤与证据隔离

复用阶段5已经冻结的10341条生成查询，来源5183篇静态SciFact文档。已有MSMARCO MiniLM只给“生成查询—来源文档”打分，max384/batch24；没有把claim标签送给模型。共 **{score['pairs']}** 对、**{score['batches']}** 个batch、**{score['padded_input_tokens']}** padded input token，累计评分与接口转换 **{score['seconds']:.2f}秒**，不含模型加载；[原始分数](stage6/scored-queries.json)全部保留。

分数为未经本域校准的相关性logit，不是证据支持概率。分位阈值在全体source-query分数上计算，与tuning/dev标注无关；没有照抄上游不同模型在MSMARCO上的数值阈值。50/70/90分位使用原版`>=t`，遇分数相等可略多于目标比例保留。

评分输入包含原标题与摘要；建索引时仅在原摘要body追加选中查询，**标题权重仍为2、原摘要权重仍为1**。不重复标题来改变原参照权重。无查询保留的文档仍以原文进入索引，始终保留全部5183篇候选。

原Corpus、摘要句子编号、核验与引用工具不变；生成查询只存在于FTS索引。测试通过扩展词检索到文档后，引用仍只能来自原始句子，不能把伪查询引用成原文。原阶段3/4/5冻结代码、模型与Agent配置继续保留。

## tuning选型与全部dev结果

预先固定五个候选，按tuning NDCG@10、其次MRR、Recall排序，指标完全相同时优先追加查询较少的配置；原BM25也可被选择。源码/模型/数据/runtime在[评分前协议](stage6/plan.json)冻结；tuning选中 **{NAMES[selected]}** 后，[dev前锁定](stage6/locked-before-dev.json)记录选择与全部tuning输出hash，再运行完整dev。

| split | 方法 | Recall@10 | MRR@10 | NDCG@10 | 单查询毫秒 |
|---|---|---:|---:|---:|---:|
{chr(10).join(results)}

tuning80条中46条、dev300条中188条有相关证据标注并进入排序指标；另34/112条不强行按无相关文档算0。所有候选使用相同查询、完整目录、K10及原评价实现。公开dev已在历史阶段多次使用，因此这是描述性比较，不声称独立测试或在线收益。

## 保留率与索引成本

| 方法 | 实际logit阈值 | 追加查询数 | 有追加查询的文档数 | SQLite非空闲页MiB | 总分配页MiB | 建索引秒 |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(footprint)}

SQLite尺寸为本机FTS数据库page_count/freelist_count/page_size计算值，含原文、FTS内部结构与元数据；每条件均执行相同更新/optimize流程。它不同于原论文的Lucene压缩索引，不能套用其索引节省比例。在线检索仅运行BM25；生成与过滤均是离线成本。之前教师批内生成/解码约107秒也是查询资产成本，虽然本轮复用了已有输出，也没有把它算成免费。

计时batch1、排除一次预热，包含查询处理/FTS/查表；每方法固定顺序单次运行，没有随机顺序性能基准。较小毫秒差异不用于声称稳定速度优势。

## 同查询配对

| 前者减后者 | 指标 | 平均差 | 描述性95%区间 | 提高/下降/相同 |
|---|---|---:|---|---|
{chr(10).join(pair_table)}

主决策依据冻结的tuning选择。70分位过滤作为预先列出的文献相关设置，与全部查询扩展另列对照；其余完整条件也保留，未从dev挑最好配置替换tuning选择。[逐查询配对](stage6-paired.json)使用10000次配对query bootstrap，seed20261025；区间不包括训练模型的不确定性，也未按共享文档聚类，不作普遍显著性证明。

## 验证和复现

[46项测试记录](stage6/tests.log)包含上游Git blob校验、真实类调用、阈值相等保留、query分数组对齐、NaN/缺失数据拒绝，以及原文引用隔离；既有预算/训练/解码检查一起运行。来源与许可详见[THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES.md)，命令见[README](../README.md)。原始预测会重新计分，并复核历史冻结资产与评分/选择hash。

这是直接复用成熟组件的一次低成本验证，没有新增训练循环或手写BM25/Agent框架；论文方法在本数据和预算下的效果以本表为准，不搬用上游宣称的提升数字。
'''
    target = Path("reports/阶段6_开源过滤组件复用.md")
    target.write_text(report, encoding="utf-8")
    print(json.dumps({"report": str(target), "selected_on_tuning": selected,
                      "dev": {n:r['summary'] for n,r in data['dev'].items()},
                      "p70_vs_all": comparisons['p70-minus-all']['ndcg']}, ensure_ascii=False))


if __name__ == "__main__":
    main()
