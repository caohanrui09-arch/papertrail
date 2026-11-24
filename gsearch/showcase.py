"""Offline, train-selected demonstration of existing paper recommendation tools.

No new scorer, Agent loop or evaluation is introduced. Personal outputs remain
inside ignored data/; each method reads and verifies only its first returned v1.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile

DEFAULT_ASOF = '2025-02-23T13:28:26.401006+08:00'


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_receipt(path: Path, groups: tuple[str, ...]) -> int:
    receipt = json.loads(path.read_text(encoding='utf-8'))
    checked = 0
    for group in groups:
        for name, expected in receipt[group].items():
            asset = Path(name)
            if not asset.is_file() or file_hash(asset) != expected:
                raise ValueError('Frozen delivery asset missing or changed: ' + name)
            checked += 1
    return checked


def preflight() -> dict:
    required = ('reports/stage15/final-validation.json', 'reports/stage15/evaluation-plan.json',
        'reports/stage15/locked-before-dev.json', 'reports/stage13/corpus-receipt.json',
        'reports/stage13/resource-10000.json', 'data/stage13-expansion/documents.json',
        'data/stage13-expansion/catalog-10000.json', 'data/stage9-recommendation/train.csv',
        '.cache/stage11/deps/sklearn/__init__.py')
    missing = [p for p in required if not Path(p).is_file()]
    if missing:
        raise FileNotFoundError('Missing local assets: ' + ', '.join(missing) +
            '. See docs/REPRODUCIBILITY.md. The demo does not download or fabricate missing assets.')
    checked = verify_receipt(Path(required[0]), ('outputs', 'code', 'report'))
    from .benchmark_cold_fusion import check_plan, methods_for
    from .content_recommendation import sklearn_runtime
    from .expansion_data import read, DATA
    check_plan(); methods_for('dev')  # Validate frozen tuning choice and its receipts.
    receipt = read(Path('reports/stage13/corpus-receipt.json'))
    if file_hash(DATA / 'documents.json') != receipt['documents_sha256'] or file_hash(DATA / 'catalog-10000.json') != receipt['catalogs']['10000']:
        raise ValueError('Frozen version corpus/catalog changed')
    runtime = sklearn_runtime()
    import importlib.metadata as metadata
    import platform
    return {'status': 'ready', 'checked_stage15_assets': checked,
        'stage15_receipt_sha256': file_hash(Path(required[0])), 'corpus_verified': True,
        'python': platform.python_version(), 'packages': runtime['packages'] | {
            name: metadata.version(name) for name in ('torch', 'transformers', 'smolagents')},
        'network_requests': 0, 'fresh_machine_install_tested': False}


def create_run_dir(output: Path | None = None) -> Path:
    root = Path('data').resolve()
    if output is None:
        parent = root / 'showcase'; parent.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix='run-', dir=parent))
    target = output.resolve()
    if target == root or not target.is_relative_to(root):
        raise ValueError('Personal demo output must be a new subdirectory of ignored data/')
    target.mkdir(parents=True, exist_ok=False)
    return target


def choose_user(users: list[str]) -> str:
    if not users:
        raise ValueError('No training-profile users')
    return min(users, key=lambda user: hashlib.sha256(('stage16-demo:' + user).encode()).hexdigest())


def fenced(text: str) -> str:
    # Untrusted source text stays literal even if an abstract contains Markdown fences.
    longest = max((len(x) for x in re.findall(r'`+', text)), default=0)
    fence = '`' * max(3, longest + 1)
    return fence + 'text\n' + text + '\n' + fence


def render_demo(payload: dict) -> str:
    lines = ['# 论文推荐与原摘要读取：本机离线演示', '',
        '这是固定历史、固定时间下的单用户示例，不是评测或线上效果。此文件含个人派生结果，仅留本地data/。', '',
        fenced('user_id=' + payload['user_id'] + '\nas_of=' + payload['as_of']), '',
        '三个方法复用同一训练历史、已读过滤、逐时点目录与官方v1。新融合权重来自冻结tuning。每路只对第一篇重新读取并核验原始响应。', '']
    for method, run in payload['methods'].items():
        lines += ['## ' + method, '']
        for number, paper in enumerate(run['recommendation']['papers'], 1):
            lines.append(f"{number}. arXiv {paper['doc_id']}v{paper['version']} — {paper['source_url']}")
        original = run['original_version_abstract']
        lines += ['', '第一篇原始标题与摘要：', '']
        if original:
            lines += [fenced(original['title'] + '\n\n' + original['abstract']), '',
                f"原响应核验：{original['source_verified']}；版本：v{original['version']}；语义立场核验：{original['semantic_stance_verified']}。", '']
        else:
            lines += ['此时点没有可返回的未读论文，未读取原文。', '']
    lines += ['## 能力边界', '',
        '- 本演示调用原生smolagents工具，展示推荐→原摘要读取；没有运行新的LLM策略评测。',
        '- 使用提交日结束+24h可用性代理，不能宣称已证明历史实际入库。',
        '- SciFact上的T5生成式检索是独立链路，本演示没有把其权重套到万篇arXiv目录。',
        '- 单次演示不用于比较算法质量或服务延迟；正式结果见阶段14/15冻结报告。',
        '- 完整工具轨迹在同目录demo.json；默认服务仍为内容推荐，cold_aware为冻结研究对照。', '']
    return '\n'.join(lines)


def run_tools(model: object, user: str, at: str, alpha: float, k: int) -> dict:
    from .expansion_discovery import ExpansionSession, make_tools
    result = {}
    for name, method, weight in (('content', 'content', 0.), ('original_rrf', 'hybrid', .5), ('cold_aware', 'cold_aware', alpha)):
        session = ExpansionSession(model, user, at, method, weight)
        tools = {tool.name: tool for tool in make_tools(session)}
        recommendation = tools['recommend_papers'](k=k)
        papers = recommendation['papers']
        original = tools['read_paper'](doc_id=papers[0]['doc_id']) if papers else None
        if original and (original['version'] != 1 or not original['source_verified']):
            raise ValueError('Original source/version verification failed')
        result[name] = {'recommendation': recommendation, 'original_version_abstract': original, 'trace': session.trace}
    return result


def verify_demo(model: object, payload: dict, alpha: float) -> int:
    if payload['research_alpha'] != alpha or set(payload['methods']) != {'content', 'original_rrf', 'cold_aware'}:
        raise ValueError('Demo methods or frozen research alpha changed')
    verified = 0
    for name, mode, weight in (('content', 'content', 0.), ('original_rrf', 'hybrid', .5), ('cold_aware', 'cold_aware', alpha)):
        run = payload['methods'][name]; recommendation = run['recommendation']
        papers = recommendation['papers']
        if recommendation['user_id'] != payload['user_id'] or recommendation['as_of'] != payload['as_of']:
            raise ValueError('Demo request identity changed')
        expected = model.recommend(payload['user_id'], payload['as_of'], mode, max(1, len(papers)), weight)
        if papers != expected:
            raise ValueError('Demo ranking differs from frozen scorer')
        original = model.read(papers[0]['doc_id'], payload['as_of']) if papers else None
        if original != run['original_version_abstract']:
            raise ValueError('Demo original abstract differs from parsed official source')
        trace = run['trace']
        if [r['tool'] for r in trace] != (['recommend_papers', 'read_paper'] if papers else ['recommend_papers']):
            raise ValueError('Demo native tool sequence differs')
        if trace[0]['result'] != recommendation or (papers and trace[1]['result'] != original):
            raise ValueError('Demo native tool trace result differs')
        verified += bool(original)
    return verified


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--check-only', action='store_true'); p.add_argument('--user')
    p.add_argument('--at', default=DEFAULT_ASOF); p.add_argument('--k', type=int, choices=range(1, 11), default=3)
    p.add_argument('--output-dir', type=Path)
    args = p.parse_args()
    checked = preflight()
    if args.check_only:
        print(json.dumps(checked, ensure_ascii=False)); return
    from .cold_fusion import load
    from .expansion_data import read, save
    from .expansion_recommendation import signature
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=1):
        model = load()
        expected = read(Path('reports/stage13/resource-10000.json'))['model_signature']
        if signature(model) != expected:
            raise ValueError('Frozen training-only fit changed')
        user = args.user if args.user is not None else choose_user(model.users)
        alpha = read(Path('reports/stage15/locked-before-dev.json'))['diagnostic_alpha']
        methods = run_tools(model, user, args.at, alpha, args.k)
        if signature(model) != expected:
            raise ValueError('Demo mutated the frozen fitted model')
        payload = {'user_id': user, 'as_of': args.at, 'methods': methods,
            'user_choice': 'explicit argument' if args.user else 'minimum hash over training-profile users only',
            'cold_user': user not in model.user2row, 'research_alpha': alpha,
            'official_catalog_versions': 10000, 'preflight': checked,
            'new_network_requests': 0, 'model_signature_unchanged': True,
            'not_a_quality_or_latency_benchmark': True}
    folder = create_run_dir(args.output_dir)
    save(folder / 'demo.json', payload)
    (folder / 'DEMO.md').write_text(render_demo(payload), encoding='utf-8')
    print(json.dumps({'output_directory': str(folder), 'demo': str(folder / 'DEMO.md'),
        'methods': list(methods), 'verified_originals': sum(bool(v['original_version_abstract']) for v in methods.values()),
        'network_requests': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
