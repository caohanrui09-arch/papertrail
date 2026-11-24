"""Build the stage-2 report from completed runs, retaining unsuccessful cases."""
import json
from pathlib import Path


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def percent(value: float) -> str:
    return f"{100 * value:.1f}%"


def main() -> None:
    variants = [("frozen", "冻结NLI＋相关性候选句组"), ("adapted", "训练适配NLI＋候选句组"),
                ("rationale", "训练证据句选择器＋适配NLI")]
    table = []
    results = {}
    for split in ("tuning", "dev"):
        for key, label in variants:
            result = load(f"reports/verifier-{key}-{split}/scores.json")
            results[(key, split)] = result
            metric = result["abstract_with_stance"]
            table.append(f"| {split} | {label} | {result['queries']} | {percent(metric['precision'])} | "
                         f"{percent(metric['recall'])} | {percent(metric['f1'])} | "
                         f"{percent(result['sentence_with_stance']['f1'])} | "
                         f"{percent(result['no_evidence_abstention_rate'])} |")
    old = load("reports/agent-final-tuning-audit/scores.json")["cases"]
    regression = load("reports/stage2-agent-regression/scores.json")["cases"]
    new = load("reports/stage2-agent-dev/scores.json")["cases"]
    if len(regression) != 4 or len(new) != 6:
        raise ValueError("Agent audits are incomplete")
    old_by_id = {case["claim_id"]: case for case in old}
    regression_rows = []
    for case in regression:
        before = old_by_id[case["claim_id"]]
        if case["has_gold_evidence"]:
            earlier = before["complete_rationale_and_stance"]
            current = case["complete_rationale_and_stance"]
        else:
            earlier = before["no_evidence_abstention"]
            current = case["no_evidence_abstention"]
        regression_rows.append(f"| {case['claim_id']} | {earlier} | {current} | "
                               f"{case['completed_protocol']} | {case['seconds']:.2f} |")
    fixed = {row["claim_id"]: row for row in results[("rationale", "dev")]["cases"]}
    raw = load("reports/verifier-rationale-dev/raw_predictions.json")["queries"]
    fixed_times = {row["claim_id"]: row["seconds"] for row in raw}
    dev_rows = []
    matched = []
    for case in new:
        reference = fixed[case["claim_id"]]
        if case["has_gold_evidence"]:
            reference_ok = reference["correct_labeled_documents"] > 0
            agent_ok = case["complete_rationale_and_stance"]
        else:
            reference_ok = not reference["evidence"] and reference["verdict"] == "INSUFFICIENT"
            agent_ok = case["no_evidence_abstention"]
        matched.append({"claim_id": case["claim_id"], "has_gold_evidence": case["has_gold_evidence"],
                        "fixed_success": reference_ok, "agent_success": agent_ok,
                        "completed_protocol": case["completed_protocol"],
                        "fixed_seconds": fixed_times[case["claim_id"]], "agent_seconds": case["seconds"]})
        dev_rows.append(f"| {case['claim_id']} | {'有' if case['has_gold_evidence'] else '无'} | "
                        f"{reference_ok} | {agent_ok} | {case['completed_protocol']} | "
                        f"{fixed_times[case['claim_id']]:.3f} | {case['seconds']:.2f} |")
    Path("reports/stage2-fixed-vs-agent.json").write_text(json.dumps(matched, indent=2), encoding="utf-8")
    final = results[("rationale", "dev")]
    frozen = results[("frozen", "dev")]
    gain = 100 * (final["abstract_with_stance"]["f1"] - frozen["abstract_with_stance"]["f1"])
    nli = load("runs/nli-scifact-seed42/run.json")
    rationale = load("runs/rationale-scifact-seed42/run.json")
    positive_hits = sum(c["complete_rationale_and_stance"] for c in new if c["has_gold_evidence"])
    negative_hits = sum(bool(c["no_evidence_abstention"]) for c in new if not c["has_gold_evidence"])
    text = f"""# 第二阶段：证据选择与核验改进

实验运行：2026-10-24；结果复核与交付：2026-10-25（Asia/Hong_Kong）。

本轮保留原来的 **T5生成式搜索＋Agent**，补上独立的文献重排、证据句选择与立场判断。完整300条dev查询上的“完整证据＋正确立场”文档级Micro-F1从 **{percent(frozen['abstract_with_stance']['f1'])}** 升至 **{percent(final['abstract_with_stance']['f1'])}**，增加 **{gain:.1f}个百分点**。句级证据＋立场F1从 **{percent(frozen['sentence_with_stance']['f1'])}** 升至 **{percent(final['sentence_with_stance']['f1'])}**。

主要收益来自训练过的证据工具。旧四例回归改善，但新六例没有显示Agent优于同模型的固定流水线；目前仍不能将系统称为可靠的科学事实核验器，也不能据此声称生成检索已超过BM25。

## 改动与复用

| 组件 | 实现与作用 |
|---|---|
| 生成式检索 | 保留原T5 4000步checkpoint与BM25/RRF，输出完整目录中的文档ID；本轮未重新训练T5 |
| 文献重排 | 冻结的MS MARCO MiniLM cross-encoder，对融合Top10重排，最多选3篇 |
| 证据句选择 | 从相同MiniLM底座单独训练二分类器，判断句子是否属于gold rationale；每篇最多3句 |
| 立场模型 | MiniLM2 NLI，先读取来源文本premise，再读取原始论断hypothesis；区分反驳、支持、证据不足 |
| Agent工具 | 新增verify_documents，保留smolagents执行循环；与搜索/读取工具共享预算 |
| 输出检查 | 最终verdict与citation ID必须匹配已记录的独立模型判断；伪造引用、改写立场、未检查自由结论会被拒绝 |

分工参考[SciFact官方模型流程](https://github.com/allenai/scifact/blob/68b98a56d93e0f9da0d2aab4e6c3294699a0f72e/doc/model.md)。模型、源码、许可与未采用的MultiVerS方案见[来源说明](../THIRD_PARTY_NOTICES.md)，固定revision和hash见[模型来源](stage2-model-sources.json)。没有下载已在SciFact上训练好的任务权重。

## 数据与实验协议

仍使用train/tuning/dev=727/80/300，训练ID已核对：两个新模型只使用train，与tuning/dev的ID交集为0。静态闭集目录为5183篇文档，原始test标签未公开，本轮未使用test。

NLI适配采用 **{nli['pairs_audit']['pairs']}** 对文本，600步、batch8、均衡采样三类；证据句选择器采用 **{rationale['pairs_audit']['pairs']}** 对文本，500步、batch16。负例包含未标注的检索文段、非rationale句，是弱监督，不能保证每个负例绝对不包含有效证据。训练构造、来源计数和完整ID列表写入各自run.json。

三个变体是在tuning上逐步开发的候选，未做预注册。前两个变体各搜索24组阈值，第三个搜索72组；最终模型与阈值在读取本阶段dev结果前冻结，见[锁定配置](stage2-locked-config.json)。80条调参查询较少，仍有过拟合风险。只有一个随机种子，未做显著性检验。

## 完整评价结果

文档级正确要求：文档属于gold、立场匹配，并覆盖至少一组完整gold证据句。每篇最多前三个预测句；句级指标同样要求完整证据组与立场匹配。下表使用SciFact-style微平均计数，未提交官方榜单。

| split | 变体 | 查询数 | 文档精确率 | 文档召回率 | 文档证据＋立场F1 | 句级证据＋立场F1 | 无证据查询拒答率 |
|---|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(table)}

最终dev有209个gold证据文档；预测199个，84个同时通过完整证据与立场要求。文档级精确率仍只有 **{percent(final['abstract_with_stance']['precision'])}**。无证据查询的拒答率从冻结参照的 **{percent(frozen['no_evidence_abstention_rate'])}** 降至 **{percent(final['no_evidence_abstention_rate'])}**，因此不是所有维度都改善。未标注但可能真实相关的文献仍按公开gold计分，没有手工宽免。

最终候选句组覆盖gold完整证据文档的上限为 **{percent(final['candidate_rationale_doc_coverage'])}**。模型得分超过0.95不代表实际正确率为95%；它只是tuning选择的未经概率校准的门槛。

详细预测：[冻结NLI](verifier-frozen-dev/scores.json)、[适配NLI](verifier-adapted-dev/scores.json)、[句选择器＋NLI](verifier-rationale-dev/scores.json)。各目录的raw_predictions.json保留生成的候选与分数；gold只用于运行结束后的计分/调参，不进入推理模型。

## 真实Agent回归

旧四例是已经看过的tuning开发样例，用于定位故障回归，不能推断总体成功率。对有证据查询，“成功”表示至少命中一组gold证据及正确立场，并不保证全部引用正确；对无证据查询则要求明确拒答且不附伪证据。

| claim ID | 首版证据判断/拒答成功 | 本轮成功 | 本轮协议完成 | 本轮秒数 |
|---|---|---|---|---:|
{chr(10).join(regression_rows)}

本轮四例均完成协议；三条有证据查询从0/3变为3/3，无证据例成功拒答。原失败轨迹保留在首版目录，新轨迹见[回归计分](stage2-agent-regression/scores.json)。这同时增加了训练数据、独立模型和输出约束，不应归因成单独的Agent规划算法收益。

## 新案例与固定流水线对照

在dev按ID选出前4条有证据查询与前2条无证据查询，运行前保存selection.json，未按成功与否挑选。新六例均完成工具协议，但4条有证据查询仅 **{positive_hits}/4** 命中完整证据＋立场，2条无证据查询 **{negative_hits}/2** 正确拒答。

下面在完全相同的六个ID上，比较本轮固定证据流水线与Agent。使用相同检查模型、阈值与每次检索Top10；固定流程执行一次检索与核验，Agent最多搜索3次、读取5篇、核验2次，总计算预算不相等。时间为本机单次观察，排除模型加载；不作为精确性能基准。

| claim ID | gold有证据 | 固定流程成功 | Agent成功 | Agent协议完成 | 固定流程秒数 | Agent秒数 |
|---|---|---|---|---|---:|---:|
{chr(10).join(dev_rows)}

六例的成功/失败结果相同，Agent增加了语言模型调用代价，**本轮没有证明Agent在这些原子论断上优于固定流水线**。它目前主要提供可检查的工具编排与补检索入口。详细对照见[逐例结果](stage2-fixed-vs-agent.json)、[Agent计分](stage2-agent-dev/scores.json)。

## 检查、资源与复现

18项正确性检查通过，见[日志](stage2-tests.log)。新增检查覆盖反向立场拒绝、虚构引用拒绝、检查器与原始claim一致性、共享预算、多句证据完整性、冻结模型权重变化拒绝，以及真实框架中错误final_answer被拦截后纠正的契约。脚本化策略仅用于契约测试，真实Agent轨迹另外保存。

训练使用RTX 4060 Laptop 8GB：NLI训练墙钟 **{nli['seconds']:.2f}秒**、峰值allocated **{nli['peak_allocated_mib']:.2f}MiB**；句选择器 **{rationale['seconds']:.2f}秒**、峰值allocated **{rationale['peak_allocated_mib']:.2f}MiB**。这是各训练进程的测量，不能当作整个系统总显存。额外参数、训练标签和计算预算必须与效果同时报告。

```powershell
# 在项目目录运行，现有模型与冻结配置已保存在本机
$py = "..\\.venv\\Scripts\\python.exe"
& $py -m unittest discover -s tests -v
& $py -m gsearch.agent --checkpoint runs/t5-dsi-4000-seed42 --verifier-config reports/stage2-locked-config.json --claim "Activation of PPM1D enhances p53 function." --output reports/new-checked-demo.json
```

完整训练/评价命令见[README](../README.md)。开启verifier-config后，最终结果位于checked_answer，状态independently_checked_prediction只表示模型与引用一致性检查通过，**不等于科学事实已证实**。检查失败或预算耗尽时checked_answer为null。

下一阶段优先处理假阳性与证据漏选，并用需要分解、比较和补检索的任务检验Agent必要性。多种子、概率校准、跨领域验证和更强生成式检索仍未完成；本轮不把这些写成已实现收益。
"""
    Path("reports/阶段2_证据核验改进.md").write_text(text, encoding="utf-8")
    print("reports/阶段2_证据核验改进.md")


if __name__ == "__main__":
    main()
