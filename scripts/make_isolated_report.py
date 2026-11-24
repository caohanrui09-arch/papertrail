"""Seal only isolated-v2 comparisons; retain invalid v1 as explicitly excluded evidence."""
import json
from pathlib import Path
from gsearch.quality_protocol import save,digest
from scripts.benchmark_isolated_constraints import ROOT,REPORT,EXTRA,fingerprints
from scripts.benchmark_state_constraints import CODE


def main() -> None:
    receipt=REPORT/'final-validation.json'
    if receipt.exists():raise ValueError('Never overwrite sealed results')
    frozen=json.loads((REPORT/'locked-before-evaluation.json').read_text())
    if fingerprints()!=frozen['fingerprints']:raise ValueError('Frozen experiment changed')
    verified=json.loads((REPORT/'delivery-validation.json').read_text())
    replay=json.loads((REPORT/'replay-and-errors.json').read_text())
    evaluation=json.loads((REPORT/'evaluation-summary.json').read_text())
    tuning=json.loads((REPORT/'tuning-summary.json').read_text())
    diagnosis=json.loads((REPORT/'failure-diagnosis.json').read_text())
    if verified['status']!='passed' or replay['status']!='passed':raise ValueError('Validation incomplete')
    if evaluation['engineering_guards_all_pass']:raise ValueError('Review unexpected passing result before sealing a closed-round report')
    errors=replay['errors_all_locations']['evaluation'];interventions=evaluation['constraint_interventions']
    rows=[]
    for policy in ('fixed','llm_agent','constrained'):
        item=evaluation['methods'][policy];e=errors[policy]
        rows.append(f"| {policy} | {item['completed']}/{item['tasks']} | {item['task_success']}/{item['tasks']} | {item['valid_citations']}/{item['citations']} | {item['llm_calls']} | {item['input_tokens']}/{item['output_tokens']} | {item['mean_seconds']:.3f} | {item['p95_seconds_nearest_rank']:.3f} | {e.get('http_rejections',0)} | {e.get('rejected_parsed_proposals',0)} | {e.get('parse_errors',0)} |")
    f,o,c=(evaluation['methods'][p] for p in ('fixed','llm_agent','constrained'))
    token_ratio=(c['input_tokens']+c['output_tokens'])/(o['input_tokens']+o['output_tokens'])
    tuning_numbers=' / '.join(f"{p} {tuning['methods'][p]['task_success']}/4" for p in ('fixed','llm_agent','constrained'))
    diagnostic_rows=[]
    for p in ('fixed','llm_agent','constrained'):
        n=diagnosis['results']['evaluation'][p]['counts']
        diagnostic_rows.append(f"| {p} | {n.get('null_k_proposals',0)} | {n.get('exact_repeated_proposals',0)} | {n.get('same_id_repeated_read_proposals',0)} | {n.get('protocol_incomplete_tasks',0)} | {n.get('completed_but_controlled_target_not_met_tasks',0)} |")
    text=f'''# 第二十一阶段：状态约束 Agent 可靠性与成本

**有效结果来自 isolated-v2：默认保留固定流程，结束本轮 Agent 优化。** 已完成失败复现、原生能力调研、三组同预算对照和逐步来源/记账复核。约束有无改善以本轮有效数字为准；未达到全部预设可靠性与成本门槛，不继续按评价结果调提示词。

## 冻结后的12个描述性任务

| 策略 | 协议完成 | 任务目标成功 | 可追溯原v1引用 | LLM调用 | 输入/输出token | 平均秒 | P95秒 | HTTP拒绝 | 含提案错误步 | 解析错误步 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

协议完成指后端接受了最终提交；任务目标还核对明确的已知论文ID、来源类型和数量。两者分开计数，引用合法不表示选到了任务目标，也不表示语义相关或科学论断正确。错误列有重叠，不能相加当失败任务数；本地/原生拒绝不会成为HTTP拒绝，但仍计入提案、token和墙钟。

固定/原LLM/约束LLM使用同一万篇v1目录、训练历史与seen过滤、时间入库代理、内容推荐、冻结Qwen2.5-1.5B权重及消息适配器。4 tuning目标成功：{tuning_numbers}，即便负结果也冻结后完整跑12任务。12任务来自阶段19/20已使用的受控显式意图集合，**不是独立测试或真人主题相关性标签**；没有新增训练、新用户反馈、CTR或语义质量结论。

## 决策和收益归因

预先固定的工程门槛：目标成功数不低于固定、无预算违规、相对原LLM的平均时间/总token至少各减少20%、平均时间不超过固定5倍。

```json
{json.dumps(evaluation['engineering_guards'],ensure_ascii=False,indent=2)}
```

约束/原LLM平均耗时比={c['mean_seconds']/o['mean_seconds']:.3f}，总token比={token_ratio:.3f}；约束/固定耗时比={c['mean_seconds']/f['mean_seconds']:.1f}。这些是小样本工程点估计，不是统计非劣性或稳定生产性能。默认fixed，研究适配器与显式复现入口保留，本轮不再调参。

本阶段实际复用smolagents1.22.0原生ToolCallingAgent、工具注册、参数校验和逐步回调，没有重写Agent循环或安装依赖。GitHub交叉比较LangGraph ToolNode与Pydantic，维护、Apache2/MIT许可、固定源码blob及读取失败见[原生组件审计](stage21-isolated/upstream-audit.json)。未获得的文件不声称已核查。新代码承担项目动作资格/引用来源检查，不把开源实现包装为原创。

这是动态schema提示和运行时约束，**没有token级约束解码**。k变为必填非null整数1..3，原生负责类型/必填，项目另查范围、状态成员和嵌套引用。成功检索退出工具表，已读ID退出候选，组合允许交换检索顺序，final只引用已读原摘要且满足来源/数量要求。无gold目标ID访问、参数修补、自动选文、自动读取或代替模型提交。即使仅剩final_answer，模型仍须自己生成有效调用。

约束组有状态提示步骤={interventions.get('model_steps_with_state',0)}，单一注册工具步骤={interventions.get('single_registered_tool_steps',0)}，工具集变化={interventions.get('toolset_changes',0)}。没有逐项消融，收益属于工程约束组合，不能单归因于某个schema字段或模型推理能力提升。

## 失败复现和预算

四类原轨迹连同SHA保留在[失败重放审计](stage21-isolated/replay-and-errors.json)：k=null、重复检索、同ID重复读取提案、未获接受的最终提交。修正fixture说明：阶段19 evaluation002是读取3个不同ID，最初映射的作废批次tuning002也无同ID重复，验收因此拒绝该映射。正确样本为有效v2 tuning000原LLM同ID两次读取，其原字节已在评价前hash冻结；修正审计路径，不改实验样本、标签或统计。

| 策略 | null k提案 | 完全相同重复提案 | 同ID重复读提案 | 未完成提交任务 | 已完成但目标未达成 |
|---|---:|---:|---:|---:|---:|
{chr(10).join(diagnostic_rows)}

上述诊断可重叠；重复提案包含对被拒请求的重试，不等于后端重复执行。已完成目标不符仅基于受控known-item gold，不能延伸为主题语义选文错误。

每任务同上限：6应用尝试（含finalize）、2检索、2读取、7框架步、8生成（含原生超步兜底）、累计30000输入/1280输出token，单次输出160。约束版本地/原生拒绝也扣等价应用及类别额度；解析失败消耗生成预算。逻辑扣费可能比旧版更严格，没有额外免费资源。约束组解析提案={interventions.get('parsed_proposals',0)}、扣费={interventions.get('charged_application_attempts',0)}、含错误提案={interventions.get('proposal_rejections',0)}、本地状态拒绝={interventions.get('local_guard_rejections',0)}、原生schema/屏蔽拒绝={interventions.get('native_schema_or_mask_rejections',0)}。逐步对齐模型提案、状态快照、实际wire和后端轨迹，未发现自动调用/参数修补。

## 首批作废及修复验证

首批项目适配器原地修改FinalAnswerTool.inputs共享类字典，污染同进程的后续原LLM组。**首批全部比较作废**，见[作废声明](stage21/INVALIDATED_SCHEMA_CONTAMINATION.json)；旧冻结源码、48份轨迹和原汇总全部保留，不进入本报告比较表。这是本项目schema所有权错误，不归咎于框架原生校验。

isolated-v2在每次更新前深拷贝每个工具实例inputs。GitHub v1.22.0 default_tools.py blob62679de8与本机文件归一化LF完全一致，[独立源码核查](stage21-isolated/schema-ownership-audit.json)确认类级定义。新增跨会话/跨策略回归，全部48个有效对照请求前后断言原生默认schema不变；当前CLI也执行此断言。重跑同任务、模型、提示/预算/门槛，未做结果驱动超参搜索；日志改直接写私有文件避免终端缓冲耦合。

既有阶段19评分器原样复用，显式文件名别名视图与源JSON字节/SHA相同，实际policy字段未改，汇总恢复真实策略名。4 tuning输出先hash冻结，锁明确记录评价尚未开始；之后36正式输出全部重计分，16约束案例逐步重放。

## 交付与范围

{verified['regression_tests']}项完整回归通过；旧v1回归本身故意运行错误适配器，测试进程单测后恢复共享字典，清理列表载于delivery-validation.json。新隔离回归在执行中断言所有权，清理不会掩盖缺陷；实验使用新进程且没有测试清理补丁。旧阶段3—20、481迁移资产及独立CPU57包均未变，人工确认/标签仍0。

默认 `unified-demo.cmd fixed`；显式研究入口 `state-agent-isolated-demo.cmd` 已实际执行，完成={verified['actual_cli_completed']}、退出码={verified['actual_cli_exit_code']}，无静默兜底。说明见[isolated-v2运行文档](../docs/ISOLATED_STATE_AGENT.md)，收据见[最终验证](stage21-isolated/final-validation.json)。旧state-agent-demo.cmd只是作废v1入口，不作为有效演示推荐。

方法顺序按任务轮换。表中墙钟含HTTP、schema干预、错误、重试与同步文件日志，装载单列；单机单次、服务缓存/计时元数据、非独占GPU可影响输出与时间，不声称确定性复现每个token、隔离GPU速度或生产QPS。首批GPU快照只保留为作废批次背景，不能拿来解释v2因果加速。未删慢样本、改电源设置、清其他进程或共享CUDA环境。

私人任务、来源响应及全部模型轨迹仅留忽略的data/.cache，未发布。两次大块写入自动审核超时核查未执行后拆分成功，不是安全拒绝，无绕过。
'''
    report_path=Path('reports/阶段21_状态约束Agent可靠性与成本.md');report_path.write_text(text,encoding='utf-8')
    extra=['scripts/replay_constraint_audit.py','scripts/replay_isolated_constraints.py','scripts/isolated_state_demo.py',
        'scripts/verify_isolated_delivery.py','scripts/diagnose_isolated_results.py','scripts/make_isolated_report.py',
        'scripts/score_unified.py','state-agent-isolated-demo.cmd']
    code=list(dict.fromkeys(CODE+EXTRA+extra))
    private=[p for p in ROOT.rglob('*') if p.is_file()]+[p for p in Path('.cache/stage21-isolated').rglob('*') if p.is_file()]
    invalid=[p for folder in ('reports/stage21','data/stage21-constraints','.cache/stage21') for p in Path(folder).rglob('*') if p.is_file()]
    value={'status':'complete_fixed_default_optimization_round_closed','version':'isolated-v2',
        'default_policy':'fixed','optimization_round_closed':True,'engineering_guards_all_pass':False,
        'independent_or_semantic_quality_claim':False,'invalid_v1_metrics_used_as_evidence':False,
        'regression_tests':verified['regression_tests'],'stages3_20_unchanged':True,
        'code':{p:digest(Path(p)) for p in code},
        'outputs':{str(p):digest(p) for p in REPORT.glob('*.json') if p!=receipt},
        'private_data':{str(p):digest(p) for p in private},
        'invalidated_v1_assets':{str(p):digest(p) for p in invalid},
        'docs':{p:digest(Path(p)) for p in ('docs/ISOLATED_STATE_AGENT.md','THIRD_PARTY_NOTICES.md')},
        'report':{str(report_path):digest(report_path)}}
    save(receipt,value)
    print(json.dumps({'sealed':True,'receipt_sha256':digest(receipt),'default':'fixed','round_closed':True}),flush=True)


if __name__=='__main__':main()
