"""Seal the complete three-group experiment and its unchanged-default decision."""
import json
from pathlib import Path
from gsearch.quality_protocol import digest,save
from scripts.benchmark_state_constraints import CODE,ROOT,REPORT,fingerprints


def main() -> None:
    receipt=REPORT/'final-validation.json'
    if receipt.exists():raise ValueError('Never overwrite sealed trial')
    frozen=json.loads((REPORT/'locked-before-evaluation.json').read_text())
    if fingerprints()!=frozen['fingerprints']:raise ValueError('Frozen experiment changed')
    verified=json.loads((REPORT/'delivery-validation.json').read_text())
    replay=json.loads((REPORT/'replay-and-errors.json').read_text())
    results=json.loads((REPORT/'evaluation-summary.json').read_text())
    if verified['status']!='passed' or replay['status']!='passed':raise ValueError('Verification incomplete')
    methods=results['methods'];fixed=methods['fixed'];old=methods['llm_agent'];new=methods['constrained']
    errors=replay['errors_all_locations']['evaluation'];interventions=results['constraint_interventions']
    rows=[]
    for key in ('fixed','llm_agent','constrained'):
        item=methods[key];error=errors[key]
        rows.append(f"| {key} | {item['completed']}/{item['tasks']} | {item['task_success']}/{item['tasks']} | {item['valid_citations']}/{item['citations']} | {item['mean_seconds']:.3f} | {item['p95_seconds_nearest_rank']:.3f} | {item['input_tokens']}/{item['output_tokens']} | {error.get('http_rejections',0)} | {error.get('rejected_parsed_proposals',0)} | {error.get('parse_errors',0)} |")
    report=f'''# 第二十一阶段：状态约束Agent可靠性与成本对照

已完成四类原失败回归、开源原生能力核查、状态约束版本及三组同预算对照。**默认保持固定流程；本轮优化到此结束，不按正式结果继续调提示词或换任务。** 保留研究代码与显式复现入口，不把约束收益归为模型推理能力。

## 冻结后12个描述性任务

| 策略 | 协议完成 | 任务目标成功 | 原v1引用核验 | 平均秒 | P95秒 | 输入/输出token | HTTP拒绝 | 被拒的已解析提案 | JSON解析失败 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

三个错误列有重叠，不能相加当作失败任务数；工具在本地或框架中被拦截时HTTP拒绝可为0，仍有真实错误和生成成本。超步终止另见replay-and-errors.json。引用存在性不是语义相关性或科学真伪。协议完成与明确任务目标成功分开，不因某次引用合法就宣称找到了正确目标论文。

三组使用同一10000篇原v1目录、冻结训练历史/seen及时间代理、同一内容推荐、同一Qwen1.5B权重与模型适配器、同一4 tuning/12评价需求；意图显式给出。12任务已经用于阶段19/20，只是重复使用的受控任务，不是独立或人工相关性检验。无新人工标签、新用户反馈或新训练。

## 预先固定的工程门槛

{json.dumps(results['engineering_guards'],ensure_ascii=False,indent=2)}

门槛：成功数不低于固定、无预算违规、相对原LLM平均时间和总token均至少减少20%、相对固定均时不超过5倍。总体通过={results['engineering_guards_all_pass']}；决定={results['decision']}。这些是简单工具任务的工程点估计标准，不是统计非劣性检验。4 tuning固定4/4、原LLM2/4、约束2/4已出现负结果；仍按原计划冻结后完整评价，不挑成功案例或据结果修改标准。

## 原生组件与约束作用

实际调用既有smolagents1.22.0的ToolCallingAgent、逐步回调、工具注册、参数校验及schema生成；没有重写Agent循环或安装依赖。GitHub比较原生实现与LangGraph ToolNode的状态/错误处理，核查Apache2/MIT、维护与适配成本；Pydantic/jsonschema在旧GPU环境不存在，未安装。固定源码blob及失败读取在upstream-audit.json。

新增适配器把k变为必填、非空整数1..3，旧可省略k接口原样保留。成功的检索函数被移除，已读ID从候选中移除；组合允许检索顺序交换，保留剩余读取能力，最终只允许引用已读原文及满足来源/数量要求的ID。不读取gold目标ID、不自动补参数、不替模型选择论文、读取或提交。模型必须生成自己的final_answer，即使只剩一个函数可用。

这是动态schema提示与运行时执行约束，**没有token级约束解码**。嵌套enum/上下界不由原生类型校验完整执行，项目另有状态成员/范围检查。模型仍会生成未知工具、重复ID或无效JSON，均保留。单一注册函数的模型步骤={interventions.get('single_registered_tool_steps',0)}，有状态提示步骤={interventions.get('model_steps_with_state',0)}，工具集变化={interventions.get('toolset_changes',0)}。新增状态与schema组合没有逐项消融，不能单独归因到某一个子组件或宣称模型学会了规划；固定流程同时提供了不调用LLM的强参照。

## 预算、错误与数据核验

每任务最多6次应用尝试（含finalize）、2次检索、2次读取；框架7步、最多8次LLM生成（含超步兜底）、累计30000输入/1280输出token、单次输出至多160。约束版本本地/原生拒绝也扣等价应用及相应类别额度，未发送HTTP不代表免费重试；解析错误仍计LLM。约束在本地扣费可能比旧版更严格，但不会获得额外资源。超步兜底照常计费，未经协议接受的文本不算成功。

正式约束组解析提案={interventions.get('parsed_proposals',0)}、扣费={interventions.get('charged_application_attempts',0)}、提案拒绝={interventions.get('proposal_rejections',0)}、本地状态拒绝={interventions.get('local_guard_rejections',0)}、原生schema/工具屏蔽拒绝={interventions.get('native_schema_or_mask_rejections',0)}。逐步骤、实际wire请求、原始后端轨迹及状态快照重新核对，没有发现自动调用或参数修复。

既有阶段19评分器直接复用，不改源码；新私有文件视图用显式SHA把fixed/llm_agent两个旧文件名角色映射到实际策略，原JSON字节/policy字段未改，汇总恢复实际名字。48份新实验输出保留，其中正式36份完整重计分，原v1由冻结评分器重新解析。四类原始失败的原路径/hash固定保留，脚本模型仅用于回归测试，与真实Qwen对照区分。

## 成本与复现限制

请求计时包括状态干预/HTTP/错误/重试；模型装载单列。方法顺序逐任务轮换，缓存/计时元数据仍会进入观察，不同批次输入会略变，不能假定贪心输出逐字一致。首次索引费用可能计入首个固定请求，单机单次样本波动较大；不将旧阶段绝对时间直接相减，也不推断稳定吞吐或生产QPS。

失败调用出现很长的墙钟尾部，计时还包括同步错误日志和运行环境影响。一份正式运行中的只读快照记录GPU100%、显存7823/8188MiB（resource-observation.json）；没有建立独占GPU，也没有验证长尾的具体原因。保留所有慢样本，不通过释放显存、改电源设置或重挑样本美化时间。因此表中是实际端到端墙钟，不是隔离的GPU推理基准；相对时间差异只作当前运行描述，不能推出算法因果加速。固定流程的成功数优势本身已足以否决本轮替换，不依赖长尾耗时作唯一依据。

本轮{verified['regression_tests']}项回归通过；16个真实约束任务逐步重放；旧阶段3—20资产、481项原迁移资产和独立CPU57包未变。人工相关性标签仍0。服务不改，默认unified-demo.cmd fixed；约束研究入口state-agent-demo.cmd，已实际运行，完成={verified['actual_cli_completed']}、退出码={verified['actual_cli_exit_code']}，无静默替代。具体运行和范围见docs/STATE_CONSTRAINED_AGENT.md。个人模型轨迹、状态与来源只留忽略的data/.cache，未发布。

两次大块文件写入的自动审批超时均未执行；核实后拆成小块成功，不是安全拒绝，也未要求绕过审核。未取得的固定文件/许可证内容如实记来源审计。所有失败、成本和限制均保留。
'''
    report_path=Path('reports/阶段21_状态约束Agent可靠性与成本.md')
    report_path.write_text(report,encoding='utf-8')
    code=CODE+['scripts/replay_constraint_audit.py','scripts/constrained_demo.py','scripts/verify_state_delivery.py',
        'scripts/make_stage21_report.py','state-agent-demo.cmd']
    outputs=[p for p in REPORT.glob('*.json') if p!=receipt]
    private=[p for p in ROOT.rglob('*') if p.is_file()]
    private += [Path('.cache/stage21/regression-tests.log'),Path('.cache/stage21/actual-cli.log')]
    value={'status':'complete_fixed_default_optimization_round_closed','regression_tests':verified['regression_tests'],
        'default_policy':'fixed','optimization_round_closed':True,'independent_or_semantic_quality_claim':False,
        'engineering_guards_all_pass':results['engineering_guards_all_pass'],'stages3_20_unchanged':True,
        'code':{p:digest(Path(p)) for p in code},'outputs':{str(p):digest(p) for p in outputs},
        'private_data':{str(p):digest(p) for p in private},
        'docs':{'docs/STATE_CONSTRAINED_AGENT.md':digest(Path('docs/STATE_CONSTRAINED_AGENT.md'))},
        'report':{str(report_path):digest(report_path)}}
    save(receipt,value)
    print(json.dumps({'sealed':True,'receipt_sha256':digest(receipt),'default':'fixed','round_closed':True}),flush=True)


if __name__=='__main__':main()
