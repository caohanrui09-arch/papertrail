"""Seal exact-replay, paired timings, source verification and real CLI receipts."""
import ast
import contextlib
import hashlib
import inspect
import json
from pathlib import Path
import subprocess
import sys
import unittest

import numpy as np
import pandas as pd

from gsearch.catalog_audit import digest
from gsearch.expansion_data import ORIGINAL, read, save
from scripts.benchmark_indexed_expansion import ROOT, DATA, CODE, OLD_ROOT, OLD_DATA, freeze, frozen_history


def main():
    if (ROOT / 'final-validation.json').exists():
        raise ValueError('Refuse to overwrite sealed validation')
    freeze()
    result = read(ROOT / 'benchmark.json')
    if result['plan_sha256'] != digest(ROOT / 'evaluation-plan.json'):
        raise ValueError('Benchmark plan mismatch')
    audit = read(ROOT / 'upstream-audit.json')
    source_path = Path(np._core.numeric.__file__)
    normalized = source_path.read_bytes().replace(b'\r\n', b'\n')
    blob = hashlib.sha1(b'blob ' + str(len(normalized)).encode() + b'\0' + normalized).hexdigest()
    if np.__version__ != audit['numpy']['version'] or blob != audit['numpy']['blob']:
        raise ValueError('Installed NumPy source differs from pinned release')
    remote = ast.parse(audit['numpy']['core_excerpt']).body[0]
    local = ast.parse(inspect.getsource(inspect.unwrap(np.flatnonzero))).body[0]
    remote.decorator_list = []; local.decorator_list = []
    if ast.dump(remote, include_attributes=False) != ast.dump(local, include_attributes=False):
        raise ValueError('flatnonzero source AST differs')
    count = 0
    for key, receipt in result['exact_replay'].items():
        split, method = key.split('/')
        name = f'10000-{method}-{split}.npz'
        if digest(DATA / name) != receipt['new_sha256'] or digest(OLD_DATA / name) != receipt['original_sha256']:
            raise ValueError('Prediction receipt drift')
        with np.load(DATA / name, allow_pickle=False) as new, np.load(OLD_DATA / name, allow_pickle=False) as old:
            np.testing.assert_array_equal(new['indices'], old['indices'])
            if len(new['indices']) != receipt['events']:
                raise ValueError('Event denominator differs')
        count += receipt['events']
    rows = read(DATA / 'paired-latency-requests.json')
    if len(rows) != 256 * 2 * 5 * 2:
        raise ValueError('Latency rows missing')
    for method, record in result['paired_uncached_latency'].items():
        for engine in ('original', 'indexed'):
            values = [r['ms'] for r in rows if r['method'] == method and r['engine'] == engine]
            actual = {'mean_ms': float(np.mean(values)), 'median_ms': float(np.median(values)), 'p95_ms': float(np.quantile(values, .95))}
            if actual != record[engine]:
                raise ValueError('Raw timing recount differs')
    # Full suite is captured locally; scripted Agent observations can contain local examples.
    with (DATA / 'tests.log').open('w', encoding='utf-8') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        suite = unittest.defaultTestLoader.discover('tests')
        tests = unittest.TextTestRunner(stream=log, verbosity=1).run(suite)
    if not tests.wasSuccessful():
        raise ValueError('Full test suite failed; see ignored local tests.log')
    train = pd.read_csv(ORIGINAL / 'train.csv', dtype={'user_id': str, 'arxiv_id': str})
    # Train-only user choice, independent of future labels or recommendation success.
    users = set(train.loc[train.rating == 1, 'user_id'])
    user = min(users, key=lambda u: hashlib.sha256(('stage14-cli:' + u).encode()).hexdigest())
    demo_path = DATA / 'cli-smoke.json'
    command = [sys.executable, '-m', 'gsearch.indexed_expansion', '--user', user,
        '--at', '2025-02-23T13:28:26.401006+08:00', '--method', 'hybrid', '--k', '3',
        '--read-top1', '--output', str(demo_path)]
    with (DATA / 'cli.log').open('w', encoding='utf-8') as log:
        subprocess.run(command, check=True, stdout=log, stderr=log)
    demo = read(demo_path)
    abstract = demo['original_version_abstract']
    if not abstract['source_verified'] or abstract['version'] != 1:
        raise ValueError('Real tool source verification failed')
    if [x['tool'] for x in demo['trace']] != ['recommend_papers', 'read_paper']:
        raise ValueError('Genuine tool sequence differs')
    frozen_history()
    cost = result['index_cost']
    latency = result['paired_uncached_latency']
    table = []
    for method in ('popular', 'sar', 'content', 'hybrid'):
        x = latency[method]
        table.append(f"| {method} | {x['original']['mean_ms']:.3f} | {x['indexed']['mean_ms']:.3f} | {x['mean_speedup']:.2f}× | {x['original']['p95_ms']:.3f} | {x['indexed']['p95_ms']:.3f} |")
    eligibility = latency['eligibility']
    report = f'''# 第十四阶段：保持推荐排名一致的请求过滤加速

1万篇共享目录的推理加速已完成。全部46,352条tuning和49,533条dev事件、12份方法输出，共{count:,}个事件—方法排名，Top10顺序及空位逐项一致。没有重新训练、调整融合、改变论文ID/版本、过滤规则或默认入口；这是服务成本改进，不是推荐质量提升。dev继续是已使用的描述性回放。

## 改动与开源复用

原实现每个候选重复调用同一个when.timestamp()，并逐篇检查训练正负seen。独立适配器把训练已读论文预映射为int32位置数组；请求时一次时间转换、原生NumPy向量比较、索引置False、flatnonzero返回升序位置。原SAR、内容评分、稳定排序、RRF及原v1读取全部沿用阶段13函数。稀疏seen索引不是评分/排名缓存；没有申请用户数×目录大小的稠密矩阵。

GitHub对比NumPy原生布尔索引/flatnonzero与pandas membership实现；两者BSD3、未归档、近期有维护。固定NumPy2.5.4 commit a3d0ef1df045b858e68115001fdabc930bb3b68c，numeric.py blob {blob}；本机文件只因Windows CRLF不同，归一化换行后整文件Git blob一致，flatnonzero AST也一致。实际调用现有NumPy，未复制算法或安装/升级依赖；pandas每请求构建membership不是本轮选择。来源、许可全文、备选源码摘要及成本见[开源审计](stage14/upstream-audit.json)。

适配器仅服务**冻结历史与目录快照**。历史/目录更新后必须重建适配器，当前不支持在线可变反馈。原拟合数组共享，避免再复制488MiB SAR矩阵。

## 同时点配对无缓存成本

沿用阶段13固定hash抽样256条请求，预先固定2轮、batch1、CPU单数值线程；轮换方法并交替新旧先后顺序。每次重新算分和排序，不缓存用户分数、日期掩码或排名。原模型装载/拟合、seen索引构建和原摘要读取不在服务计时内，分别记账。这里比较**本轮同进程配对测量**；不能与上一阶段另一时段的绝对毫秒数直接相减。

| 方法 | 原版均值ms | 索引版均值ms | 均值加速 | 原版P95ms | 索引版P95ms |
|---|---:|---:|---:|---:|---:|
{chr(10).join(table)}

单独过滤均值{eligibility['original']['mean_ms']:.3f}→{eligibility['indexed']['mean_ms']:.3f}ms，{eligibility['mean_speedup']:.2f}×。这是本机固定请求样本的工程计时，没有多机器/跨负载置信保证；主要算分开销仍然存在。

索引构建{cost['build_seconds']:.4f}秒，存储{cost['positions']:,}个seen位置，int32载荷{cost['array_payload_bytes']/2**20:.3f}MiB。Python字典与数组对象getsizeof合计{cost['python_container_and_array_object_bytes']/2**20:.3f}MiB，**已包括数组载荷，不应再相加**；不含共享字符串键。构建前后RSS点差{cost['observed_rss_delta_bytes']/2**20:.3f}MiB，不冒充独立进程峰值。模型装载+原拟合{cost['loading_and_original_fit_seconds']:.3f}秒，非请求延迟。

## 无损与真实链路验证

- 全11,165名训练seen用户逐一比对位置集合；337个时间边界逐一覆盖前/等于/后，结合共同AND过滤验证全部目录因素。
- 完整tuning八方法及dev四方法重放，保存新的12份NPZ并独立再次对比原始输出；568,948个事件—方法排名完全相同，因而同分母Recall/NDCG、冷热组和覆盖指标均不变。
- 同一样本两轮共5,120条原始计时记录独立重算均值/中位数/P95，全部一致；计时中也逐请求对比过滤集合或排名。
- 全套{tests.testsRun}项测试通过；真实CLI使用训练期选出的用户与+08:00请求时间，调用原生smolagents recommend_papers→read_paper，重新解析缓存官方v1，source_verified=true。只验证来源和工具协议，不声称Agent决策或语义核验质量收益。
- 阶段3—13代码、数据、输出和冻结协议检查通过；本轮代码/审计/协议/结果/本地派生文件全部写入独立收据。

## 运行

```powershell
.cache/stage6-env/Scripts/python.exe -m gsearch.indexed_expansion --user USER_ID --at "2025-02-23T13:28:26.401006+08:00" --method hybrid --k 3 --read-top1 --output data/my-indexed-demo.json
```

索引仅在装载后构建一次；推荐与原摘要的用户级结果保存在忽略的data/，不分发Scholar Inbox派生记录。基准命令为python -m scripts.benchmark_indexed_expansion，完成结果拒绝覆盖；python -m scripts.make_stage14_report封存验证收据。

阶段13混合对冷论文表现偏弱的问题仍在；本轮完全相同的排名也意味着该问题没有被性能优化解决。下一轮应独立调研缺失协同分支的融合方式，预先固定少量候选，只在tuning选型、冻结后再做描述性dev；不要把本轮延迟改善当作融合质量收益。
'''
    report_path = Path('reports/阶段14_推荐请求无损加速.md')
    report_path.write_text(report, encoding='utf-8')
    source = {'numpy_version': np.__version__, 'numeric_lf_git_blob': blob, 'flatnonzero_ast_exact': True,
              'line_ending_normalization_only': True}
    save(ROOT / 'source-validation.json', source)
    save(ROOT / 'final-validation.json', {
        'tests': tests.testsRun, 'test_failures': len(tests.failures), 'test_errors': len(tests.errors),
        'source': source, 'exact_event_method_rankings': count, 'raw_prediction_files': len(result['exact_replay']),
        'changed_rankings': 0, 'original_stages3_13_unchanged': True,
        'real_cli': {'native_tools': [x['tool'] for x in demo['trace']], 'version': 1, 'source_verified': True,
                     'time_input': '+08:00', 'user_selection': 'minimum SHA256(stage14-cli:user) over train-positive users'},
        'outputs': {str(p): digest(p) for p in sorted(ROOT.glob('*.json'))},
        'code': {p: digest(Path(p)) for p in (*CODE, 'scripts/make_stage14_report.py')},
        'data': {str(p): digest(p) for p in sorted(DATA.iterdir()) if p.is_file()},
        'report': {str(report_path): digest(report_path)}})
    print(json.dumps({'tests': tests.testsRun, 'exact_rankings': count, 'report': str(report_path), 'sealed': True}))


if __name__ == '__main__':
    main()
