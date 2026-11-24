"""Render the experiment report only from completed recorded runs."""
import json
from pathlib import Path


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    audit = load("reports/data_audit.json")
    run = load("runs/t5-dsi-4000-seed42/run.json")
    retrieval = []
    for name in ["bm25-tuning", "dsi-800-tuning", "dsi-4000-tuning", "hybrid-4000-tuning",
                 "bm25-dev", "dsi-4000-dev", "hybrid-4000-dev"]:
        report = load("reports/" + name + ".json")
        summary = report["summary"]
        retrieval.append(f"| {report['split']} | {name} | {summary['judged_queries']} | "
                         f"{summary['recall@10']:.4f} | {summary['mrr@10']:.4f} | {summary['ndcg@10']:.4f} | "
                         f"{summary['mean_seconds'] * 1000:.2f} |")
    agent = load("reports/agent-final-tuning-audit/scores.json")
    if len(agent["cases"]) != 4:
        raise ValueError("Final audit not complete")
    completed = sum(c.get("completed_protocol", False) for c in agent["cases"])
    correct = sum(c["complete_rationale_and_stance"] for c in agent["cases"] if c["has_gold_evidence"])
    agent_rows = []
    for case in agent["cases"]:
        recall = case["recorded_document_recall"]
        agent_rows.append(f"| {case['claim_id']} | {'有' if case['has_gold_evidence'] else '无'} | "
                          f"{recall if recall is not None else '不适用'} | "
                          f"{case['complete_rationale_and_stance']} | {case['explicit_abstention']} | "
                          f"{case['successful_tool_calls']}/{case['failed_tool_calls']} | "
                          f"{case['model_parsing_or_execution_errors']} | {case['budget_exhausted']} |")
    text = f"""# 首版实验报告：生成式搜索 + 证据核验 Agent

日期：2026-10-24，Asia/Hong_Kong。此项目独立于根目录的生成式商品推荐教学项目。

## 已交付的内容与边界

已实现并实际运行：真实 SciFact 数据准备、BM25 参照、T5 查询生成文档 ID 的训练与完整目录解码、RRF 融合、smolagents 工具循环、真实本地指令模型、原文引用记录与离线证据计分。
这是有实验记录的首版研究实现，当前结果不能宣称生成模型超过 BM25，也不能宣称 Agent 已具备可靠的科学证据判断能力。

本项目学习的是“查询→文档”的生成式搜索；Agent 维护的是检索与证据状态。另一项目学习的是“交互历史→商品”的生成式推荐，Agent 维护偏好与商品排除条件。模型结构、任务数据、训练目标、工具和评价均分开。

## 数据协议与复现

- 官方原始 corpus **{audit['documents']}** 篇文档，完整候选空间，不采样负例。
- train/tuning/dev **727/80/300** 条；带证据标注 **459/46/188** 条。移除 train 中与 dev 文本相同的 claim 871、1291；规范化查询文本交集为 0。
- 内部 tuning 用于训练预算和 Agent 提示调试；官方 dev 用于冻结检索配置后的描述性评价。原始官方 test 标签未公开，未读取 test。
- 静态 corpus 的标题与摘要可用于索引学习，包括 dev 相关文档；训练不读取 dev 的查询和证据标签作梯度更新。这是闭集检索，不是新文档泛化。
- corpus 指纹 `{audit['corpus_fingerprint']}`，数据和模型来源/hash 见 [数据审计](data_audit.json)、[模型来源](model_sources.json)、[配置锁定](locked_config.json)。原始数据 hash 是本次官方下载快照的本地记录。
- 代码复用与三类数据许可见 [来源说明](../THIRD_PARTY_NOTICES.md)。SciFact 的 `evidence` 同时包含支持和反驳文档，相关不等于支持。

## 检索结果

| split | 实验文件名 | 有相关标注文档的查询数 | Recall@10 | MRR@10 | NDCG@10 | 单查询平均 ms |
|---|---|---:|---:|---:|---:|---:|
{chr(10).join(retrieval)}

BM25 使用 Python SQLite FTS5 的 Porter 分词与标题权重2/摘要权重1；生成检索使用 T5-small 全参数训练，beam=10；RRF 为两路 Top10 等权融合、常数60。所有方法使用同一目录、相关集合和 K。有效和唯一槽位率在这些运行中均为100%；非法或重复结果仍消耗排名位置。

T5 增加训练后相关文档召回提高，但仍弱于 BM25。等权 RRF 在 dev 的 Recall 略高于 BM25，MRR/NDCG 更低，且 tuning 上不占优；不能挑一个数字宣称整体胜出。当前只有一个种子，未做显著性检验或线上评价。

没有标注证据的查询不被硬算成 Recall=0，它们在检索表外单独统计；Agent 诊断中仍保留这类查询。SciFact 部分文献可能存在未标注的证据，评价受公开标注完整性限制。

计时为 batch=1，排除一次预热，包含分词、生成与查表；完整神经 dev 评价时没有同时训练或运行 Agent。800步早期诊断与 Agent 初始化曾有时间重叠，该轮延迟仅作开发记录。不同调用的缓存、温度与调度波动使微小延迟差异不能当作速度收益。

## 训练与设备

- RTX 4060 Laptop 8 GB，Windows，Python/依赖见 [环境](environment.json)。
- T5-small：**{run['trainable_parameters']:,}** 个可训练参数，全参数更新；固定seed42，batch8，max input160，lr0.0005，BF16 autocast。
- 4000步：index **{run['exposures']['index']}** 次、query **{run['exposures']['query']}** 次曝光，503个训练query–document对；另存800步诊断checkpoint。
- 训练进程峰值 CUDA allocated **{run['peak_allocated_mib']:.2f} MiB**。4000步墙钟 **{run['seconds']:.2f} 秒**，前段同时进行早期 Agent 调试；该时间不作为独占GPU吞吐。allocated 不等于整机总显存。
- checkpoint、tokenizer、固定base revision和完整loss序列保存到 runs/；检查点与corpus指纹不匹配时拒绝检索。

## 真实 Agent 诊断

使用独立 **Qwen2.5-1.5B-Instruct** 策略，smolagents ToolCallingAgent 执行。预先按 tuning 的ID选出有证据的69/112/138与无证据的15。调试期间看过这些案例，以下是开发诊断，不能当独立测试成功率。

四例中 **{completed}/4** 完成工具协议；三条有证据查询中，**{correct}/3** 同时命中完整证据句组与正确立场。代码链路已运行，事实核验效果没有通过这一轮诊断。

| claim ID | gold有证据 | 已记录文档Recall | 覆盖一组证据句且立场正确 | 明确拒答 | 工具成功/失败调用 | 解析/执行错误步骤 | 步数耗尽 |
|---|---|---:|---|---|---:|---:|---|
{chr(10).join(agent_rows)}

所有完整轨迹和对应计分见 [最终四例诊断](agent-final-tuning-audit/scores.json)。每例最多3次搜索、5次读取、8个框架步骤。初始 hybrid 会实际调用T5；模型可改写查询、切换检索器和决定是否继续。没有将gold传给Agent工具，标注仅在运行结束后计分。

具体失败位置：69选择了不相关文档5389095，而候选中有gold文档；112找对文档6157837，却把gold的CONTRADICT判成SUPPORT；138找对文档26016929和反驳方向，却选了句6，没有覆盖gold句7和9；15最终耗尽步骤且未正确明确拒答。这些失败分别涉及候选选择、方向判断、证据句定位和停止决策，不能靠合法文档ID或引用存在性检查解决。

证据工具从原文句子编号构造引用，确保ID与原文可追溯；`source_verified=true` **不代表语义正确**。模型可能选择不相关文献、误判否定方向或证据不足时给出结论。原始回答是待核验实验输出，引用存在与证据/立场命中分别报告。

早期0.5B两次实测失败，保留 `agent-local-first.json` 与 `agent-05b-native-adapter.json`。1.5B通用提示诊断只完成第一例，第二例反复格式错误后中断，见 `agent-tuning-audit/`；不得把未完成的四例声明为完整对照。旧领域提示四例保留在 `agent-domain-tuning-audit/`。随后去掉不适用的框架工具示例、统一JSON观察格式，并修复停止标记与换行在同一token时未停的问题，最终版再跑同样四例。调试记录说明适配风险，不支持总体改善幅度结论。

## 正确性与后续研究边界

独立项目 **8 项检查通过**，日志见 [检查记录](correctness-tests.log)。涵盖排名分母、重复/非法排名、查询转义、先检索后读取再引用、句子边界与布尔/负数拒绝、预算、框架调用契约、decoder start边界及工具停止标记换行。新增依赖后，原商品推荐项目7项检查也通过。

当前尚缺：多种子、更多Agent案例、独立的证据相关性/立场模型或人工核验、预算公平的单次检索与多步Agent对照、真正改善生成检索的query-generation/语义编码实验。这些都不能写成已完成收益。部署时也不能让未核验的科学论断直接成为用户结论。

运行命令、模型下载与模块说明见 [README](../README.md)。数据、权重和原始文献受各自许可约束；代码记录不包含论文全文抓取或在线收益。
"""
    Path("reports/实验报告.md").write_text(text, encoding="utf-8")
    print("reports/实验报告.md")


if __name__ == "__main__":
    main()
