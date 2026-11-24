"""Recount, verify historical seals and seal the actual unified-chain delivery."""
import json
from pathlib import Path
import subprocess

from .prepare_stage19_tasks import ROOT, digest, save
from .benchmark_unified import CODE, fingerprints
from .score_unified import score


def main() -> None:
    receipt = Path('reports/stage19/final-validation.json')
    if receipt.exists(): raise ValueError('Do not overwrite sealed stage19')
    frozen = json.loads(Path('reports/stage19/locked-before-evaluation.json').read_text())
    if fingerprints() != frozen['fingerprints']: raise ValueError('Evaluation configuration drift')
    for name, value in frozen['tuning_outputs'].items():
        if digest(Path(name)) != value: raise ValueError('Tuning outputs changed')
    recomputed = score('evaluation')
    stored = json.loads(Path('reports/stage19/evaluation-summary.json').read_text())
    if recomputed != stored: raise ValueError('Independent full raw recount differs')
    tests = json.loads(Path('reports/stage19/regression-validation.json').read_text())
    api = json.loads(Path('reports/stage19/api-policy-validation.json').read_text())
    http = json.loads(Path('reports/stage19/http-validation.json').read_text())
    if not tests['passed'] or not api['passed'] or http['status'] != 'passed': raise ValueError('Verification failed')
    smoke = json.loads(Path('reports/stage19/delivery-smoke.json').read_text())
    lifecycle = json.loads(Path('reports/stage19/lifecycle-validation.json').read_text())
    if not smoke['default_fixed_passed'] or not smoke['llm_mode_explicit_no_silent_fallback'] or not lifecycle['restarted_ready']:
        raise ValueError('Actual CLI/lifecycle acceptance incomplete')
    from gsearch.benchmark_cold_fusion import history
    from gsearch.showcase import verify_receipt
    from gsearch.relocated_demo import verify_bundle
    history()
    counts = {}
    for n, groups in [(15, ('outputs','code','data','report')), (16, ('code','materials','outputs','private_data','report')),
                      (17, ('code','docs','outputs','report','private_replay_assets')), (18, ('code','docs','outputs','report'))]:
        counts[str(n)] = verify_receipt(Path(f'reports/stage{n}/final-validation.json'), groups)
    from .manage_stage17_env import BASE, VENV, environment
    bundle = verify_bundle(BASE / 'replica')
    code = "import importlib.metadata as m,json;print(json.dumps({d.metadata['Name']:d.version for d in m.distributions()}))"
    process = subprocess.run([str(VENV/'Scripts/python.exe'), '-E', '-s', '-c', code],
        env=environment(), check=True, capture_output=True, text=True)
    installed = json.loads(process.stdout)
    if installed != json.loads(Path('reports/stage17/runtime-versions.json').read_text())['installed_versions']:
        raise ValueError('Independent service environment changed')
    from gsearch.unified_agent import request
    code, health = request('GET', '/health')
    if code != 200 or health['candidates'] != 10000: raise ValueError('Unified service is not ready')
    from .local_service_control import request as old_request
    if old_request('GET', '/health')[0] != 200: raise ValueError('Prior service unavailable at acceptance')
    from .unified_service_control import STATE
    state = json.loads(STATE.read_text())
    if state['instance_id'] != health['instance_id']: raise ValueError('Owned instance differs')
    overlay = json.loads(Path('.cache/stage19/overlay.json').read_text())
    if any(digest(Path(name)) != value or digest(BASE/'replica'/name) != value for name, value in overlay.items()):
        raise ValueError('Served overlay differs from checked source')
    native = stored['methods']
    fixed, llm = native['fixed'], native['llm_agent']
    report = f'''# 第十九阶段：万篇统一搜索、推荐与原摘要引用Agent

已接通共同10000篇arXiv明确v1目录上的BM25搜索、个性化推荐、原摘要读取和带ID/版本/URL的摘录回答。固定流程与真实Qwen/smolagents工具循环共享同一服务和工具上限。当前配置下是否采用LLM由下表判断；**默认保留固定流程，未声称LLM调度收益**。

## 正式受控对照

| 指标 | 固定流程 | Qwen1.5B工具Agent |
|---|---:|---:|
| 任务数 | {fixed['tasks']} | {llm['tasks']} |
| 完成来源协议 | {fixed['completed']} | {llm['completed']} |
| 满足任务目标/路由/引用数 | {fixed['task_success']} | {llm['task_success']} |
| 可核验引用 | {fixed['valid_citations']}/{fixed['citations']} | {llm['valid_citations']}/{llm['citations']} |
| 服务工具尝试总数（含错误/最终提交） | {fixed['server_attempts']} | {llm['server_attempts']} |
| 其中失败尝试 | {fixed['failed_attempts']} | {llm['failed_attempts']} |
| LLM调用 | {fixed['llm_calls']} | {llm['llm_calls']} |
| 输入/输出token | {fixed['input_tokens']}/{fixed['output_tokens']} | {llm['input_tokens']}/{llm['output_tokens']} |
| 请求平均耗时（秒） | {fixed['mean_seconds']:.3f} | {llm['mean_seconds']:.3f} |
| 请求P95 nearest-rank（秒） | {fixed['p95_seconds_nearest_rank']:.3f} | {llm['p95_seconds_nearest_rank']:.3f} |

分意图结果见stage19/evaluation-summary.json。失败全部在分母；引用0条时不以0/0声称100%准确。统计为单次、12项、显式意图的受控已知条目/工具路由评价，没有显著性或一般化保证。搜索任务使用原始标题，不等同于自然主题相关性检索评测；推荐任务检查真实推荐工具及原文引用，**没有人工相关性或满意度gold**。引用核验是原始文本存在性，不是语义支持度、科学结论正确性、全文阅读或自由摘要生成评价。该集合不冒充新独立评分时段，原dev仍仅描述性。

LLM分组成功：标题搜索3/3、推荐0/3、组合2/3、空结果0/3。典型失败包括重复调用推荐、不必要重复读取、空查询任务生成k=null而被严格拒绝，继而耗尽预算。不能将这些失败隐藏成固定流程的成功，或把已核验引用率视作全部任务完成率。

## 目录、时间和开源复用

- 沿用冻结万篇明确v1、原始ID/用户历史、默认content推荐；搜索和推荐都使用同一available_at及train正负seen。可用时间仍是v1提交日结束+24h代理，不能称已证实历史入库。
- SQLite3.45.1 FTS5原生bm25(0,2,1)、porter unicode61、稳定ID并列序；只对当时可用文档建立索引，未来论文不进入IDF。按可用ID集合LRU至多2份索引，所有用户共享该时点统计；SQL在LIMIT前剔除seen。首次建索引与快照命中费用在原始响应分别记录。正式对照使用已加载服务/已热索引，模型一次装载耗时另列runtime.json，不计为请求耗时，不推断生产QPS。
- GitHub交叉比较bm25s（MIT）、rank_bm25（Apache2）、SQLite（公开领域）、smolagents（Apache2）和LangGraph（MIT），固定源码/许可/维护与适配成本见upstream-audit.json。实际调用现有SQLite和smolagents1.22.0，不重写BM25/Agent循环、不安装或升级包。SAR/sklearn/arxiv.py及来源哈希验证沿用原组件。
- CPU服务继续使用阶段17独立运行时，57个包版本逐一未变、481项旧迁移资产未改。Qwen读取已有冻结revision989aa798，推理只读复用旧stage6/shared CUDA环境；不把LLM推理也宣称为完全独立运行时。权重逐文件SHA在冻结和评价入口核验。

## 预先冻结与失败记录

先从训练历史/目录按hash构造4个tuning、12个evaluation任务，目标含warm/old_cold/new_cold及未知用户，未按检索成功率筛选、未读未来评分。gold只由评分器读取，策略只收相同intent/query/instruction。调试后locked-before-evaluation保存所有代码、任务、历史收据和模型来源hash，正式评价入口及本次封存再次逐项核验，无评价后调参。

首轮通用消息适配与第二轮Qwen原生消息适配均LLM0/4完成，固定均4/4；原始失败、token和时间完整保留。旧适配的tool-response按普通user传输，新增独立历史格式适配使用冻结Qwen chat_template的tool格式，移除重复synthetic Calling tools并补全历史分隔符，不修复非法生成JSON，也不改旧冻结代码。格式修正没有消除重复检索，因此只追加一次明确顺序提示，最后tuning为LLM1/4、固定4/4，随后停止调试并冻结。三轮tuning不能作为独立效果证据。

还保留：任务准备cohort名误猜，源实际new_cold，两个中间文件留benchmark-preparation-incomplete；后改为全组成功后才写文件。一次写文件自动审批超时，确认未执行后原样重试成功，未绕过拒绝。

## 服务、验证和运行

新服务仅127.0.0.1:8766，原8765不改；64会话、15min TTL、6次总工具尝试（含finalize）、2次检索/2次读取，失败计费。先返回再读取；最终最多两篇已读取、不同ID的明确v1原摘要摘录。错误引用、布尔索引、未读引用、未来/已读结果、会话过期和超预算被拒绝。模型不执行生成代码、文件系统命令或网络搜索。

实际通过：{tests['tests']}项完整回归、{http['checks']}项真实HTTP、{api['tests']}项原生API状态测试；6组原版BM25在同as-of目录上ID与分数精确一致；正式原始输出重新计分和{stored['independently_parsed_raw_responses']}份官方响应原生重解析；阶段3—18冻结资产全部不变。TTL用可控时钟测试，不声称真实等待15分钟。启动/CLI演示记录见delivery-smoke.json。

入口：unified-service.cmd start/status/stop；unified-demo.cmd fixed或llm_agent。详细命令见docs/UNIFIED_SERVICE.md。LLM不稳定时保留失败和退出码，不静默替换为固定流程。个人任务、轨迹、摘要、完整模型输出留忽略的data/.cache，不对外发布。尚无新独立真实反馈、线上业务收益或万篇T5生成检索训练；原SciFact生成式检索实验维持独立边界。
'''
    report_path = Path('reports/阶段19_统一搜索推荐与Agent对照.md')
    save(Path('reports/stage19/history-validation.json'), {'stages3_18_unchanged': True,
        'checked_assets_stages15_18': counts, 'migrated_bundle_assets': len(bundle['files']),
        'independent_cpu_packages_unchanged': len(installed), 'serving_overlay_exact': True,
        'both_local_services_ready_at_acceptance': True})
    report_path.write_text(report, encoding='utf-8')
    code_files = [Path(p) for p in CODE] + [Path('scripts/check_stage19_regression.py'),
        Path('scripts/smoke_unified_delivery.py'), Path('scripts/validate_unified_lifecycle.py'), Path(__file__),
        Path('unified-service.cmd'), Path('unified-demo.cmd')]
    outputs = [p for p in Path('reports/stage19').glob('*.json') if p != receipt]
    private = [p for p in ROOT.rglob('*') if p.is_file()]
    private += list(ROOT.parent.glob('demo-*/result.json'))
    private += [p for p in (ROOT.parent/'benchmark-preparation-incomplete').rglob('*') if p.is_file()]
    private += [Path('.cache/stage19/http-responses-private.json'), Path('.cache/stage19/regression-tests.log'), Path('.cache/stage19/api-policy-tests.log')]
    private += [Path('.cache/stage19/cli-fixed.log'), Path('.cache/stage19/cli-llm_agent.log')]
    result = {'status': 'passed', 'tests': tests['tests'], 'http_checks': http['checks'], 'api_policy_tests': api['tests'],
        'raw_evaluation_outputs_recounted': 24, 'stages3_18_unchanged': True,
        'fixed_task_success': fixed['task_success'], 'llm_task_success': llm['task_success'], 'tasks_per_policy': fixed['tasks'],
        'default_policy': 'fixed', 'independent_feedback_claim': False, 'semantic_correctness_claim': False,
        'code': {str(p): digest(p) for p in code_files}, 'outputs': {str(p): digest(p) for p in outputs},
        'private_data': {str(p): digest(p) for p in private},
        'docs': {'docs/UNIFIED_SERVICE.md': digest(Path('docs/UNIFIED_SERVICE.md'))},
        'report': {str(report_path): digest(report_path)}}
    save(receipt, result)
    print(json.dumps({'status': 'sealed', 'receipt_sha256': digest(receipt), 'fixed': fixed['task_success'], 'llm': llm['task_success']}), flush=True)


if __name__ == '__main__': main()
