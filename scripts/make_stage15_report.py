"""Seal bounded cold-fusion findings; retain content as conservative serving default."""
import contextlib
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

import numpy as np

from gsearch.catalog_audit import digest
from gsearch.expansion_data import read, save
from gsearch.expansion_recommendation import signature
from gsearch.content_recommendation import sklearn_runtime
from gsearch.cold_fusion import load
from gsearch.benchmark_cold_fusion import ROOT, DATA, CODE, ALPHAS, check_plan, history, acceptance
from scripts.validate_cold_fusion import source_runtime, validate_outputs
from scripts.make_stage9_report import paired


def selection_check(lock: dict) -> None:
    content = read(ROOT / 'content-tuning.json'); costs = read(ROOT / 'latency-tuning.json')['methods']
    results = {f'gated_a{round(a * 100)}': read(ROOT / f'gated_a{round(a * 100)}-tuning.json') for a in ALPHAS}
    checks = {name: acceptance(r, content, costs[name], costs['content']) for name, r in results.items()}
    if checks != lock['acceptance_by_candidate']:
        raise ValueError('Acceptance cannot be reproduced')
    feasible = [name for name, result in checks.items() if result['passed']]
    def key(name):
        s = results[name]['summary']
        return s['ndcg@10'], s['recall@10'], s['mrr@10'], -results[name]['mode_and_alpha'][1]
    chosen = max(feasible or list(results), key=key)
    if chosen != lock['selected_for_research'] or bool(feasible) != lock['passes_tuning_acceptance']:
        raise ValueError('Tuning selection differs')


def main() -> None:
    if (ROOT / 'final-validation.json').exists():
        raise ValueError('Refuse to overwrite completed report')
    plan = check_plan(); lock = read(ROOT / 'locked-before-dev.json')
    selection_check(lock)
    sklearn_runtime()
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=1):
        source = source_runtime(); model = load()
        before = signature(model)
        checked, users = validate_outputs(model)
        if signature(model) != before:
            raise ValueError('Validation mutated fitted model')
        paired_results = {'gated_minus_content': paired(users['dev', 'gated'], users['dev', 'content']),
                          'gated_minus_plain': paired(users['dev', 'gated'], users['dev', 'plain']),
                          'rrf_minus_content': paired(users['dev', 'rrf'], users['dev', 'content'])}
        save(ROOT / 'paired-aggregate.json', paired_results)
        dev = {name: read(ROOT / f'{name}-dev.json') for name in ('content', 'rrf', 'plain', 'gated')}
        costs = read(ROOT / 'latency-dev.json')['methods']
        dev_guards = acceptance(dev['gated'], dev['content'], costs['gated'], costs['content'])
        mean = paired_results['gated_minus_content']['ndcg']['mean_delta']
        interval = paired_results['gated_minus_content']['ndcg']['bootstrap_95_percentile_interval']
        verdict = '已观察到描述性NDCG正差且用户配对区间高于0，但dev重复使用，仍需要新时段验证。' if interval[0] > 0 else (
            '主比较NDCG区间跨0，未确认稳定质量收益。' if interval[1] >= 0 else '主比较NDCG区间完全低于0，所选方案在该描述性窗口退化。')
        save(ROOT / 'decision.json', {'tuning_passed': lock['passes_tuning_acceptance'], 'dev_descriptive_guards': dev_guards,
            'primary_ndcg_delta': mean, 'primary_ndcg_bootstrap_95_interval': interval,
            'serving_choice': 'content', 'verdict': verdict,
            'reason': 'default fixed to content before dev; this repeated development set is not independent evidence for promotion',
            'research_alpha': lock['diagnostic_alpha'], 'no_dev_reselection': True})
        # Train-only user, independent of future likes and recommendation success.
        user = min(model.users, key=lambda u: hashlib.sha256(('stage15-cli:' + u).encode()).hexdigest())
    demos = {}
    for method in ('recommended', 'cold_aware'):
        output = DATA / f'cli-{method}.json'
        command = [sys.executable, '-m', 'gsearch.cold_fusion', '--user', user,
            '--at', '2025-02-23T13:28:26.401006+08:00', '--method', method, '--k', '3', '--read-top1', '--output', str(output)]
        with (DATA / f'cli-{method}.log').open('w', encoding='utf-8') as log:
            subprocess.run(command, check=True, stdout=log, stderr=log)
        demo = read(output)
        if not demo['original_version_abstract']['source_verified'] or demo['original_version_abstract']['version'] != 1:
            raise ValueError('Original-v1 tool source failed')
        names = [r['tool'] for r in demo['trace']]
        if names != ['recommend_papers', 'read_paper']:
            raise ValueError('Native tool trace differs')
        actual = demo['recommendation']['papers'][0]['method']
        if actual != ('content' if method == 'recommended' else method):
            raise ValueError('Conservative default/experimental method differs')
        demos[method] = {'actual_method': actual, 'tools': names, 'source_verified': True, 'version': 1}
    with (DATA / 'tests-final.log').open('w', encoding='utf-8') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        tests = unittest.TextTestRunner(stream=log, verbosity=1).run(unittest.defaultTestLoader.discover('tests'))
    if not tests.wasSuccessful():
        raise ValueError('Full test suite failed')
    history()
    quality_rows, cost_rows, tuning_rows, group_rows = [], [], [], []
    for name in ('content', 'rrf', 'plain', 'gated'):
        r = dev[name]; s = r['summary']; cold = r['event_groups']['cold_item']; warm = r['event_groups']['warm_item']
        quality_rows.append(f"| {name} | {s['recall@10']:.6f} | {s['ndcg@10']:.6f} | {cold['hits']}/{cold['events']} | {cold['ndcg']:.6f} | {warm['recall']:.6f} | {warm['ndcg']:.6f} | {s['catalog_coverage']:.2%} |")
        c = costs[name]; cost_rows.append(f"| {name} | {c['mean_ms']:.3f} | {c['median_ms']:.3f} | {c['p95_ms']:.3f} |")
        for group, values in r['user_groups'].items():
            group_rows.append(f"| {name} | {group} | {values['users']} | {values['recall']:.6f} | {values['ndcg']:.6f} |")
    for alpha in ALPHAS:
        name = f'gated_a{round(alpha * 100)}'; r = read(ROOT / f'{name}-tuning.json')
        failed = [key for key, ok in lock['acceptance_by_candidate'][name]['checks'].items() if not ok]
        tuning_rows.append(f"| {alpha:g} | {r['summary']['recall@10']:.6f} | {r['summary']['ndcg@10']:.6f} | {r['event_groups']['cold_item']['hits']} | {'通过' if not failed else ', '.join(failed)} |")
    audit = read(ROOT / 'tuning-mechanism-audit.json')
    delta_rows = []
    for name, values in paired_results.items():
        for metric in ('recall', 'ndcg'):
            d = values[metric]; lo, hi = d['bootstrap_95_percentile_interval']
            delta_rows.append(f"| {name} | {metric} | {d['mean_delta']:+.6f} | [{lo:+.6f}, {hi:+.6f}] | {d['wins']}/{d['losses']}/{d['ties']} |")
    total = sum(r['events'] for r in checked.values())
    warm_cold_effect = dev['gated']['event_groups']['cold_item']['hits'] - dev['plain']['event_groups']['cold_item']['hits']
    report = f'''# 第十五阶段：冷论文掉榜归因与融合受控对照

已完成tuning机制审计、开源组件交叉核查、三权重受控实验、冻结后dev、归一化消融和真实工具链验证。研究对照固定协同权重{lock['diagnostic_alpha']:g}；tuning验收{'通过' if lock['passes_tuning_acceptance'] else '未通过，保留内容推荐'}。{verdict} **默认推荐继续使用content，未按dev另挑参数或切换旧Agent。**

## 掉榜机制：没有协同证据，却有任意协同排名

先只读取tuning：28,180条全局无训练点赞论文事件，内容命中20、原alpha.5 RRF命中1，19次内容命中掉出Top10；原始逐案数据留在忽略的data/。20次命中内容排名1—8，零协同分排名8634—9420，融合后10—65。中位内容rank5、CF rank9172.5、融合rank26.5。逐案核验CF rank=严格正分候选数+零分项按基础ID的并列位置。

旧RRF把零分当作分支中真实存在的排序项。冷论文只有内容证据，内容项被乘0.5，同时热论文可以获得两路靠前贡献；零分ID排序还引入任意的协同次序。因此**不能把掉榜全部归因于ID并列次序**，缺失分支的权重损失与热论文两路加分也同时存在。单纯删除冷论文CF的尾部贡献未必改善，必须做受控对照。

## 开源选择与唯一方案族

对比MIT ranx固定7363db0的RRF、MIT PyTerrier-alpha0.16.5固定1a11ef94的RRF/PerQueryMaxMinScore，以及BSD3 sklearn1.9.1固定866c0f51的归一化核心。ranx仅对run里存在的项贡献排名；PyTerrier RRF外连接后缺失贡献填0，两者都不会自动把显式数值0识别为缺失。PyTerrier rank从0开始，与原RRF的1起始偏移不同，所以旧参照保持原实现和k60。

ranx需要当前没有的Numba/llvmlite；没有为这轮引入JIT依赖。实际试用PyTerrier-alpha包装器因validate导入错误失败，该失败保留在审计/notes中，未偷偷修补或声称包装器可运行。它的归一化实现委托sklearn minmax_scale，本轮直接调用现有原生函数。实际安装的_data.py经CRLF转LF后Git blob {source['native_minmax_source_lf_git_blob']}与固定上游一致。没有新安装、复制融合算法、修改共享CUDA环境或启动JVM；来源、许可及适配边界见[开源审计](stage15/upstream-audit.json)。

唯一新增方案族为**按可用分支权重归一化的分数融合**，门控是本项目适配，不包装为上游已有冷启动算法。只在当前已入库且未读候选上分别调用minmax_scale得到z_cf、z_text。support=论文是否在原SAR训练词表中，alpha只取0.25/0.5/0.75：

```text
score = (alpha * support * z_cf + (1-alpha) * z_text)
        / (alpha * support + 1-alpha)
```

热论文两路融合；冷论文等价只取z_text。**已知热论文分数0仍然有分支支持**，不将其误当缺失。常数向量由原生minmax_scale输出0，最终并列仍按基础ID。alpha0端点完全复用content，冷用户及零内容画像沿用原回退，不伪造个性化。配套plain消融在同一归一化/alpha下不做支持门控，区分分数归一化与门控本身的影响。

## 固定协议与tuning选型

沿用阶段13的10000篇官方明确v1目录、同一train、词表/画像、所有正负seen过滤、as-of代理；通过阶段14稀疏索引加速。未来论文只transform，归一化极值只能看当前eligible项。仍不回写tuning/dev交互，不改变目录、领域或时间假设。公开dev已经用过，本轮仍只描述性；指标是每条正反馈事件的singleton排序，先用户内后跨用户宏平均，不能与旧整期列表NDCG混比。目录外/未入库论文仍计miss。

三个gated权重才参与选型，plain仅作匹配消融。预先固定工程点估计门槛：总体Recall/NDCG及冷论文组不低于内容；热论文与热用户Recall/NDCG至少为内容的95%；同进程配对平均/P95延迟不超过内容1.5倍。这些不是统计不劣效检验。可行候选按NDCG→Recall→MRR→更小alpha选择；若全失败，仅冻结最佳诊断alpha进行dev，推荐仍保留content。全部代码、数据引用、失败结果和权重在locked-before-dev封存后才运行dev。

| 协同权重 | tuning Recall宏平均 | tuning NDCG宏平均 | 冷论文命中数 | 验收／失败项 |
|---|---:|---:|---:|---|
{chr(10).join(tuning_rows)}

研究冻结项{lock['selected_for_research']}，alpha={lock['diagnostic_alpha']:g}；未依据dev重选。tuning参照内容NDCG={read(ROOT / 'content-tuning.json')['summary']['ndcg@10']:.6f}。

## 冻结后的描述性dev结果

全部49,533条点赞、3,587名用户保留。主指标为用户宏平均；论文冷热与交叉组为事件微平均，分母明确。eligible冷论文子组另存在JSON，不能替代完整分母。

| 方法 | Recall宏平均 | NDCG宏平均 | 冷论文命中/完整分母 | 冷论文NDCG微平均 | 热论文Recall微平均 | 热论文NDCG微平均 | 推荐覆盖 |
|---|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(quality_rows)}

同一alpha下，gated相对plain的冷论文命中变化为{warm_cold_effect:+d}次；该消融才用于判断门控贡献。与旧RRF的差还混合了分数尺度与融合方式改变，不能全部归功于门控。无训练点赞的目录外论文仍不可召回，该方案没有解决目录覆盖上限。

| 方法 | 用户组 | 人数 | Recall宏平均 | NDCG宏平均 |
|---|---|---:|---:|---:|
{chr(10).join(group_rows)}

## 配对差异和成本

10000次用户配对bootstrap，第一项gated-content为主比较，其他为机制对照；用户为重采样单位。区间是当前重复使用窗口上的不确定性描述，不恢复独立测试资格，也不对多个探索比较作普遍显著性结论。

| 比较 | 指标 | 平均差 | 95%用户配对区间 | 提高/下降/相同用户 |
|---|---|---:|---|---|
{chr(10).join(delta_rows)}

dev门槛核查{'通过' if dev_guards['passed'] else '未通过'}，失败项：{', '.join(k for k,v in dev_guards['checks'].items() if not v) or '无'}。这项核查只报告冻结方案的表现，不用于重选alpha或替换方案。

固定hash请求tuning128/dev256，各2轮、batch1、CPU单数值线程，轮换并反转方法次序；不缓存评分/排名，不把质量回放的64用户批处理和日排名复用当服务耗时。装载/拟合、索引构建、原摘要读取排除在本表外。

本轮请求样本和机器运行状态与阶段14不同，绝对毫秒数不直接跨阶段比较；成本保护依据本轮同进程、同请求的配对比例。

| 方法 | dev均值ms | 中位数ms | P95ms |
|---|---:|---:|---:|
{chr(10).join(cost_rows)}

## 验证、运行与结论

{tests.testsRun}项全套测试通过；12份预测、{total:,}个事件—方法排名独立以原始ID逐行重新计分，核对原分母、时间、正负seen、无重复/空位、冷热组/覆盖及全部用户指标。192次原生无缓存排名再演一致，原内容与原RRF完整回放逐项复现。两组原始计时独立重算一致，阶段3—14代码/数据/输出冻结检查通过。原始用户/案例/预测/CLI记录仅存在忽略的data/。

真实CLI两次验证：recommended确实选择content，显式cold_aware使用冻结研究alpha；两者均经原生smolagents recommend_papers→read_paper重新解析缓存官方v1，source_verified=true。只证明来源和工具链，不声称Agent策略或语义核验质量提高。

```powershell
# 默认保留内容推荐
.cache/stage6-env/Scripts/python.exe -m gsearch.cold_fusion --user USER_ID --at "2025-02-23T13:28:26.401006+08:00" --method recommended --k 3 --read-top1 --output data/my-cold-fusion-demo.json
# 显式运行冻结研究方案：把--method改为cold_aware
```

完整复现为python -m gsearch.benchmark_cold_fusion --phase plan/tuning/lock/dev依次分开执行，结果与协议拒绝覆盖；python -m scripts.make_stage15_report封存报告。阶段13提交日结束+24h依旧只是可用性代理，非历史公告/实际入库证明；元数据不代表PDF全文授权，Scholar Inbox非商用/禁止派生分发边界继续遵守。

本轮已解释冷论文的掉榜机制，并完成固定范围的方案验证。{verdict} 内容仍作为默认，停止这轮权重搜索，不继续依据dev添加候选；后续若要声称可泛化收益，需要新的未参与选型时间段。
'''
    report_path = Path('reports/阶段15_冷论文融合归因与对照.md')
    report_path.write_text(report, encoding='utf-8')
    receipt = {'tests': tests.testsRun, 'test_failures': len(tests.failures), 'test_errors': len(tests.errors),
        'source_runtime': source, 'raw_outputs_rescored': checked, 'event_method_rankings': total,
        'stages3_14_unchanged': True, 'model_signature_unchanged': True, 'selection_reproduced': True,
        'real_cli': demos, 'dev_descriptive_only': True, 'serving_choice': 'content',
        'outputs': {str(p): digest(p) for p in sorted(ROOT.glob('*.json'))},
        'code': {p: digest(Path(p)) for p in (*CODE, 'scripts/validate_cold_fusion.py', 'scripts/make_stage15_report.py')},
        'data': {str(p): digest(p) for p in sorted(DATA.iterdir()) if p.is_file()},
        'report': {str(report_path): digest(report_path)}}
    save(ROOT / 'final-validation.json', receipt)
    print(json.dumps({'tests': tests.testsRun, 'rankings_rescored': total, 'verdict': verdict, 'report': str(report_path)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
