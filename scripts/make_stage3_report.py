"""Render paired bundle outcomes and resource receipts without success filtering."""
import json
from pathlib import Path


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def main() -> None:
    scores = load("reports/stage3-dev/scores.json")["policies"]
    names = {"single_pass": "固定Top3流程", "rule_adaptive": "规则自适应", "llm_agent": "大模型Agent"}
    if set(scores) != set(names) or any(result["tasks"] != 12 for result in scores.values()):
        raise ValueError("All three policies must finish the same 12-task evaluation")
    manifest = load("reports/stage3-dev/manifest.json")
    locked = load("reports/stage3-locked-protocol.json")
    for key in ("code_hashes", "ceilings", "task_ids", "tasks_audit_sha256", "verifier_config_sha256"):
        if manifest[key] != locked[key]:
            raise ValueError(f"Evaluation differs from locked protocol: {key}")
    aggregate = []
    resources = []
    for policy, name in names.items():
        row = scores[policy]
        aggregate.append(f"| {name} | {row['completed_tasks']}/12 | {row['successful_tasks']}/12 | "
                         f"{percent(row['claim_success_rate'])} | {percent(row['document_evidence_f1'])} | "
                         f"{row['mean_seconds']:.2f} | {row['budget_violations']} |")
        classifier_pairs = sum(sum(v["pairs_processed"] for v in case["classifier_work"].values())
                               for case in row["cases"])
        generative = sum(case["tool_usage"]["generative_searches"] for case in row["cases"])
        resources.append(f"| {name} | {row['total_searches']} | {generative} | {row['total_assessments']} | "
                         f"{row['total_document_claim_pairs']} | {classifier_pairs} | "
                         f"{row['total_llm_input_tokens']} / {row['total_llm_output_tokens']} |")
    by_task = {policy: {case["task_id"]: case for case in score["cases"]} for policy, score in scores.items()}
    paired = []
    pairs_json = []
    for task_id in manifest["task_ids"]:
        case = {policy: by_task[policy][task_id] for policy in names}
        paired.append(f"| {task_id} | {case['single_pass']['task_success']} | {case['rule_adaptive']['task_success']} | "
                      f"{case['llm_agent']['task_success']} | {case['llm_agent']['completed_protocol']} | "
                      f"{case['llm_agent']['llm_usage'].get('calls', 0)} |")
        pairs_json.append({"task_id": task_id, "policies": {p: {"success": c["task_success"],
                           "completed": c["completed_protocol"], "seconds": c["seconds"],
                           "tool_usage": c["tool_usage"], "llm_usage": c["llm_usage"]} for p, c in case.items()}})
    comparisons = []
    comparisons_json = {}
    for control in ("single_pass", "rule_adaptive"):
        wins = sum(by_task["llm_agent"][t]["task_success"] and not by_task[control][t]["task_success"]
                   for t in manifest["task_ids"])
        losses = sum(by_task[control][t]["task_success"] and not by_task["llm_agent"][t]["task_success"]
                     for t in manifest["task_ids"])
        ties = 12 - wins - losses
        comparisons.append(f"- 相对{names[control]}：Agent胜{wins}、负{losses}、相同{ties}个任务。")
        comparisons_json[control] = {"agent_wins": wins, "agent_losses": losses, "ties": ties}
    Path("reports/stage3-paired-outcomes.json").write_text(json.dumps({"paired": pairs_json, "comparisons": comparisons_json},
                                                                     indent=2), encoding="utf-8")
    failures = []
    top2 = load("reports/stage3-posthoc-top2/scores.json")
    same_top2 = 0
    for task_id in manifest["task_ids"]:
        original = load(f"reports/stage3-dev/{task_id}-llm_agent.json")["checked_results"]
        control = load(f"reports/stage3-posthoc-top2/{task_id}.json")["checked_results"]
        same_top2 += original == control
    for task_id in manifest["task_ids"]:
        if not by_task["llm_agent"][task_id]["completed_protocol"]:
            raw = load(f"reports/stage3-dev/{task_id}-llm_agent.json")
            meta = raw["llm_metadata"]
            failures.append(f"- `{task_id}`：未完成协议；已用{meta.get('llm_usage', {}).get('calls', 0)}次LLM调用，"
                            f"拒绝继续生成{meta.get('llm_usage', {}).get('denied_calls', 0)}次。"
                            f"错误类型/预算信息见该任务原始轨迹，未用兜底文本替代合格答案。")
    failure_text = "\n".join(failures) if failures else "本轮Agent均完成协议；这不代表其证据判断均正确，质量仍按gold单独计分。"
    text = f"""# 第三阶段：双论断调度与相同预算上限对照

日期：2026-10-25（Asia/Hong_Kong）。

本轮回答一个限定问题：在保留T5生成式搜索和阶段2证据模型的条件下，跨两条论断分配检索与核验预算，是否需要大模型Agent？三种策略在**完全相同的12个任务、24条原始论断**上运行，使用相同工具服务、模型和预算上限。实际消耗另报，没有把相同上限写成相同已用算力。

## 任务来源与适用范围

输入来自原SciFact的dev；各split先按原文文本去重、按ID排序、seed20261025打乱，每两条一组。构造不看gold标签，也不按既有模型的成功/失败筛选。完整构造包含tuning40组、dev150组，本轮预先固定tuning前4组调试和dev前12组评价；每条原子论断在同一split内仅使用一次。

这是一项**受控组合与调度诊断**：A/B两条独立原文明确给出，策略决定先检查谁、如何补检索、如何分配剩余预算及何时停止。它不评估自由文本分解正确率，也不是自然多跳推理数据集。原始数据许可仍适用，见[来源说明](../THIRD_PARTY_NOTICES.md)。

调研了[HoVer官方协议](https://hover-nlp.github.io/)：真实多跳任务依赖对应Wikipedia语料，与当前科学文献目录和闭集T5索引不同，本轮没有混用或声称复现HoVer。引用质量与结论正确性分开报告借鉴[ALCE](https://github.com/princeton-nlp/ALCE)的评价分工，没有复制其代码或数据。

公开任务只含原文A/B和任务说明，gold单独存放。所有策略运行结束后才打开gold计分。构造hash见 `data/stage3-bundles/audit.json`，固定任务ID、预算、模型配置与代码hash见[锁定协议](stage3-locked-protocol.json)。本轮gold标签分布为 `{json.dumps(scores['single_pass']['claim_verdict_distribution'], ensure_ascii=False)}`；这是随机配对后观察到的分布，不是平衡抽样。

## 三个对照策略

| 策略 | 行为 |
|---|---|
| 固定Top3流程 | A/B各一次hybrid_checked搜索、各核验Top3，总计最多6文档-论断对 |
| 规则自适应 | A/B初始各核验Top2；剩余容量按INSUFFICIENT状态给未解决条目，BM25补检索并排除已核验文档 |
| 大模型Agent | 复用smolagents执行循环，由Qwen2.5-1.5B-Instruct选择claim、查询、方法、文档与停止时机 |

每任务共享硬上限：**4次搜索、4次核验调用、累计6文档-论断对**。重复或缓存命中的核验仍扣额度；每次hybrid_checked使用T5/BM25融合Top10加相同重排器，每文档最多3句。Agent另外限**12次LLM调用、累计24000输入token、1600输出token**，包括格式重试和兜底生成；输入在forward前预留，输出参数被剩余额度实际裁剪。

每条claim有独立的已检索集合、已核验集合与引用；A搜到的文档不能直接作为B的工具输入。改写query不改检查器使用的原始论断。最终必须返回A/B两项并匹配各自的核验结果，遗漏条目、错位引用或更改立场会被拒绝。检查器本身仍可能错，模型一致性不当作gold正确。

## 完整评价结果

任务成功要求两条论断都完成协议且通过gold：有证据时，最终立场正确并至少命中一组完整gold证据；无标注证据时，要求空引用拒答。只完成一条不算整任务成功；失败/预算耗尽仍计入分母。至少一组正确不保证所有附加引用都正确，因此另外给出文档证据F1。

| 策略 | 协议完成 | 整任务成功 | 原子论断成功率 | 文档证据＋立场F1 | 单任务平均秒 | 预算违规任务 |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(aggregate)}

同ID配对结果：

{chr(10).join(comparisons)}

样本只有12组，未做多种子或显著性检验；成功数的小差异不能直接推广为总体优越性。这些组合源自此前已评价过的dev原子论断，具有任务复用局限，但任务配对、策略版本与评价ID均在本阶段dev执行前冻结，未按效果更换样本。

## 追加的事后解释性对照：固定Top2

观察原始轨迹后发现，12个任务中的Agent都只按原文查询A/B，各核验Top2，随后停止；没有进行补检索或将剩余额度分配给难项。因此另跑一个**未预注册、事后追加**的固定Top2对照，使用同样12个输入、模型、阈值和上限，完全不调用LLM。它没有用于调参、替换主结果或筛选任务。

固定Top2整任务成功 **{top2['successful_tasks']}/12**，原子论断成功率 **{percent(top2['claim_success_rate'])}**，文档证据＋立场F1 **{percent(top2['document_evidence_f1'])}**。检查后的结论和引用在 **{same_top2}/12** 个任务上与Agent完全一致；核验文档-论断对同为{top2['total_document_claim_pairs']}，但无需Agent额外的{scores['llm_agent']['total_llm_input_tokens']}输入和{scores['llm_agent']['total_llm_output_tokens']}输出token。详细结果见[事后对照](stage3-posthoc-top2/scores.json)。

这说明本轮Agent相对固定Top3多成功一个任务，不能归因为学会了自适应调度：固定Top2也能复现。事后Top2平均时间为{top2['mean_seconds']:.3f}秒；它运行时未加载LLM，显存驻留和时段与主实验不同，不将其与Agent {scores['llm_agent']['mean_seconds']:.2f}秒的比值当作严格速度倍数。当前证据支持在这组任务上优先保留简单流程，未证明大模型调度的必要性。

## 实际资源账单

| 策略 | 搜索总次数 | 其中T5生成检索 | 核验调用 | 核验文档-论断对 | 分类器文本对 | LLM输入 / 输出token |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(resources)}

分类器文本对包含文献重排、句选择和NLI，原始轨迹还记录各模型forward批次与padding后token数。上限相同不等于实际输入长度、文档选择和算力相同；表中的实际消耗用于解释取舍。模型加载不计时，分类器统一用公开tuning文本预热，每个任务/策略清空证据候选缓存，禁止跨策略复用预测。LLM首轮初始化与桌面GPU负载仍可能影响延迟，本表是单次本机观察，不外推线上吞吐。

## 逐任务结果与失败

| task ID | 固定流程成功 | 规则成功 | Agent成功 | Agent协议完成 | Agent实际LLM调用 |
|---|---|---|---|---|---:|
{chr(10).join(paired)}

{failure_text}

逐例配对与用量见[对照JSON](stage3-paired-outcomes.json)，完整分母和分项计分见[score文件](stage3-dev/scores.json)。`stage3-dev/`保存每个任务、每种策略的独立轨迹与manifest，未只保留成功案例。

## 调试过程与复现

第一轮四个tuning任务中，Agent完成3/4；一例将原文引号错误转义，反复生成非法JSON，硬token预算拒绝继续forward。完整失败轨迹保留在 `stage3-pilot/`。接口增加 `query=""` 原文句柄后，同四个调试任务全部完成；原文与gold均未改动，也未采用宽松JSON修复。两轮调试的三策略整任务成功数都是1/4，没有用失败记录筛选dev任务。

代码、提示、任务与权重配置在dev之前冻结；有变化的恢复运行会被拒绝。30项检查通过，见[测试记录](stage3-tests.log)，覆盖标签盲任务构造、子任务隔离、重复调用收费、共享预算、原文引用字符保留、LLM生成参数裁剪、缺失答案拒绝、不可用答案不获拒答分以及超预算结果不获整任务成功分。

```powershell
$py = "..\\.venv\\Scripts\\python.exe"
# 本机任务与模型已准备，运行到新目录以保留历史结果
& $py -m gsearch.benchmark_bundles --split dev --limit 12 --output reports/new-bundle-run
# 中断后，在代码/提示/模型/任务/预算未变时恢复同一目录
& $py -m gsearch.benchmark_bundles --split dev --limit 12 --output reports/new-bundle-run --resume
```

本轮不新增模型训练，不改变阶段2阈值或T5权重。下一步的研究选择应以同ID质量与实际成本为依据；若规则流程已够用，应保留它作为强参照。自然多跳任务、未见过的数据、多种子、更强生成检索和Agent策略训练仍需单独验证，不能由本次小样本组合实验替代。
"""
    Path("reports/阶段3_多论断预算对照.md").write_text(text, encoding="utf-8")
    print("reports/阶段3_多论断预算对照.md")


if __name__ == "__main__":
    main()
