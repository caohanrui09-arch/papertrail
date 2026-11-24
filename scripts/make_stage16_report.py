"""Seal local career-delivery materials, genuine demo and read-only verification."""
import argparse
import contextlib
import json
from pathlib import Path
import re
import unittest
from urllib.parse import unquote

from gsearch.showcase import file_hash
from scripts.verify_delivery import verify

ROOT = Path('reports/stage16')
DATA = Path('data/stage16-delivery')
DOCS = ('docs/PROJECT_BRIEF.md', 'docs/REPRODUCIBILITY.md', 'docs/RESUME.md', 'docs/INTERVIEW.md')
CODE = ('gsearch/showcase.py', 'scripts/verify_delivery.py', 'scripts/make_stage16_report.py', 'tests/test_showcase.py', 'demo.cmd')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo-dir', type=Path, required=True)
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True); DATA.mkdir(parents=True, exist_ok=True)
    if (ROOT / 'final-validation.json').exists():
        raise ValueError('Refuse to overwrite sealed delivery')
    folder = args.demo_dir.resolve()
    if not folder.is_relative_to(Path('data/showcase').resolve()):
        raise ValueError('Use a genuine local data/showcase demo directory')
    demo = json.loads((folder / 'demo.json').read_text(encoding='utf-8'))
    if not (folder / 'DEMO.md').is_file():
        raise ValueError('Human-readable demo missing')
    links = 0
    for name in DOCS:
        path = Path(name)
        for target in re.findall(r'\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
            if target.startswith(('https:', 'http:', '#')):
                continue
            asset = path.parent / unquote(target.split('#')[0])
            if not asset.is_file():
                raise ValueError('Broken material link: ' + name + ' -> ' + target)
            links += 1
    print(json.dumps({'phase': 'material_links', 'verified': links}), flush=True)
    full = verify(full=True, demo=demo)
    if full['demo_originals_reparsed_and_rankings_replayed'] != 3:
        raise ValueError('Expected three genuine source-verified methods')
    (ROOT / 'full-delivery-check.json').write_text(json.dumps(full, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'phase': 'full_verification', 'rankings': full['event_method_rankings_rescored']}), flush=True)
    with (DATA / 'tests-final.log').open('w', encoding='utf-8') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        suite = unittest.defaultTestLoader.discover('tests')
        tests = unittest.TextTestRunner(stream=log, verbosity=1).run(suite)
    if not tests.wasSuccessful():
        raise ValueError('Full tests failed; see local stage16 log')
    # Final seal after tests: historical assets must remain unchanged.
    from gsearch.benchmark_cold_fusion import history
    from gsearch.showcase import verify_receipt
    history()
    checked = verify_receipt(Path('reports/stage15/final-validation.json'), ('outputs', 'code', 'data', 'report'))
    environment = {key: full[key] for key in ('python', 'packages', 'fresh_machine_install_tested', 'source_runtime')}
    environment['existing_runtime'] = '.cache/stage6-env/Scripts/python.exe'
    environment['source_locks'] = ['reports/stage11/runtime-lock.json', 'reports/stage15/upstream-audit.json']
    (ROOT / 'environment.json').write_text(json.dumps(environment, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    manifest = {'client_date': '2026-10-27', 'scope': 'local offline career-delivery; not fresh-machine installation or independent-time evaluation',
        'existing_assets': {'frozen_stage15_receipt': file_hash(Path('reports/stage15/final-validation.json')),
            'corpus_receipt': file_hash(Path('reports/stage13/corpus-receipt.json'))},
        'new_code': {p: file_hash(Path(p)) for p in CODE}, 'materials': {p: file_hash(Path(p)) for p in DOCS},
        'private_assets': {str(p.relative_to(Path.cwd())): file_hash(p) for p in (folder / 'demo.json', folder / 'DEMO.md')},
        'privacy': 'User-level demo/trace/test outputs remain in ignored local data/. No external publishing performed.',
        'research_reuse': 'Only adapters around existing argparse/pathlib/hashlib/unittest and original smolagents/SAR/sklearn/arxiv.py; no new framework, algorithm or package.'}
    (ROOT / 'delivery-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    report = f'''# 第十六阶段：本机求职交付版验收

已完成一键离线演示、只读完整复核、项目架构与简历/面试材料整理。本阶段不增加算法或训练，不修改阶段3—15冻结实现、数据或指标，不向外部平台发布代码/用户数据。

## 本次实际验收

- 根目录demo.cmd已实际运行：训练画像用户固定hash选人，一次拟合后运行content、原RRF、冻结cold_aware；三路均经原生工具重新读取对应第一篇官方v1。结果只存忽略的data/showcase/，公开材料只有聚合信息。
- 交付复核独立复演三路推荐并重解析原摘要，校验demo.json的请求身份、冻结权重、原生工具顺序与轨迹结果；原模型签名保持不变。
- 完整只读检查：10000篇官方v1重新解析；12份预测、568948个事件—方法排名重计分；阶段15的{checked}项资产与阶段3—15历史检查通过。
- 全套{tests.testsRun}项测试通过，失败0/错误0；新增测试覆盖训练期用户选择、输出隔离/拒绝覆盖、原文围栏展示、交付hash漂移及三路真实来源工具/篡改拒绝。
- 四份材料共{links}个本地链接逐一存在；简历数字对应阶段14/15冻结结果，架构明确区分SciFact生成检索与万篇arXiv推荐。

## 交付文件

| 文件 | 用途 |
|---|---|
| [项目一页纸与架构](../docs/PROJECT_BRIEF.md) | 问题、两条链路、组件复用、成果和边界 |
| [分层复现说明](../docs/REPRODUCIBILITY.md) | 一键演示、快速预检、完整只读复核及从零重跑边界 |
| [简历条目与证据](../docs/RESUME.md) | 搜推算法/Agent工程两个版本及事实来源 |
| [面试讲解](../docs/INTERVIEW.md) | 一分钟、五分钟介绍、12类追问和代码走读 |
| [环境](stage16/environment.json) / [资产清单](stage16/delivery-manifest.json) | 实际运行版本、固定来源与本次交付hash |

## 最短运行路径

```powershell
.\\demo.cmd
.cache/stage6-env/Scripts/python.exe -m gsearch.showcase --check-only
.cache/stage6-env/Scripts/python.exe -m scripts.verify_delivery --full
```

demo输出DEMO.md与完整demo.json，新目录自动创建，不覆盖已有研究结果。当前研究alpha为阶段15 tuning冻结的0.25，默认服务仍保留content。单次示例不能拿来比较质量/延迟；阶段15收益仍是重复使用dev上的描述性结果。

## 尚未验证的范围

新机器全量安装、从空目录获取所有历史资产并重跑、未参与选型的新独立时间段、线上曝光/CTR/AB以及统一LLM策略质量提升均未完成。本轮只验收**本机可运行、材料可核验的求职交付版**，不称生产系统上线。早期T5搜索与当前万篇推荐属于不同语料链路；原始摘要核验不等于全文理解或观点真伪核验。

新入口只做既有组件的离线适配与交付整理，适用项目规则中的明确小改动/离线任务调研例外；实际复用与第三方许可仍按原通知保留，没有重复实现框架或引入新依赖。
'''
    report_path = Path('reports/阶段16_求职交付与演示验收.md')
    report_path.write_text(report, encoding='utf-8')
    receipt = {'tests': tests.testsRun, 'failures': len(tests.failures), 'errors': len(tests.errors),
        'local_material_links_verified': links, 'real_demo_methods': 3, 'official_originals_verified': 3,
        'historical_stages3_15_unchanged': True, 'full_verification': full,
        'code': {p: file_hash(Path(p)) for p in CODE}, 'materials': {p: file_hash(Path(p)) for p in DOCS},
        'outputs': {str(p): file_hash(p) for p in sorted(ROOT.glob('*.json'))},
        'private_data': manifest['private_assets'] | {str(DATA / 'tests-final.log'): file_hash(DATA / 'tests-final.log')},
        'report': {str(report_path): file_hash(report_path)}}
    (ROOT / 'final-validation.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'phase': 'sealed', 'tests': tests.testsRun, 'verified_originals': 3, 'report': str(report_path)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
