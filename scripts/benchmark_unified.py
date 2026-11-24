"""Run controlled tasks without loading their gold labels into either policy."""
import argparse
import hashlib
import json
from pathlib import Path
import time

from gsearch.unified_agent import load_model, run, request
from .prepare_stage19_tasks import ROOT, digest, save

CODE = ['gsearch/unified_search.py', 'gsearch/unified_session.py', 'gsearch/unified_service.py',
    'gsearch/unified_agent.py', 'gsearch/qwen_messages.py', 'gsearch/prompts/unified.txt', 'scripts/unified_service_control.py',
    'scripts/prepare_stage19_tasks.py', 'scripts/benchmark_unified.py', 'scripts/score_unified.py',
    'scripts/validate_unified_http.py', 'scripts/probe_unified_api.py', 'tests/test_unified.py']


def fingerprints() -> dict:
    files = [Path(p) for p in CODE] + [Path('reports/stage19/evaluation-plan.json'), Path('reports/stage19/upstream-audit.json')]
    files += sorted(ROOT.glob('*-tasks.json')) + sorted(ROOT.glob('*-gold.json'))
    files += sorted((ROOT / 'tuning-original-adapter').glob('*')) + sorted((ROOT / 'tuning-native-messages').glob('*'))
    files += [Path('reports/stage19/tuning-original-adapter-summary.json'), Path('reports/stage19/tuning-native-messages-summary.json')]
    files += [Path(f'reports/stage{n}/final-validation.json') for n in (15, 16, 17, 18)]
    source = Path('.cache/models/Qwen2.5-1.5B-Instruct/source.json')
    files.append(source)
    manifest = json.loads(source.read_text())
    for entry in manifest['files']:
        path = source.parent / entry['file']
        if digest(path) != entry['sha256']:
            raise ValueError('Pinned Qwen local asset changed')
    return {str(path): digest(path) for path in files}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=('tuning', 'lock', 'evaluation'), required=True)
    args = parser.parse_args()
    lock = Path('reports/stage19/locked-before-evaluation.json')
    if args.phase == 'lock':
        if lock.exists(): raise ValueError('Already frozen')
        cases = list((ROOT / 'tuning').glob('*-fixed.json')) + list((ROOT / 'tuning').glob('*-llm_agent.json'))
        if len(cases) != 8: raise ValueError('Complete all eight tuning runs first')
        save(lock, {'fingerprints': fingerprints(), 'tuning_outputs': {str(p): digest(p) for p in sorted(cases)},
            'selection': 'no parameter search; exact-title controlled protocol, original content default, prompt frozen after tuning',
            'recommendation_default_changed': False})
        print(json.dumps({'frozen': True, 'evaluation_not_run': not (ROOT / 'evaluation').exists()}))
        return
    if args.phase == 'evaluation':
        frozen = json.loads(lock.read_text())
        if frozen['fingerprints'] != fingerprints(): raise ValueError('Frozen inputs/code changed')
        for name, value in frozen['tuning_outputs'].items():
            if digest(Path(name)) != value: raise ValueError('Tuning history changed')
    elif lock.exists():
        raise ValueError('Tuning closed after freeze')
    target = ROOT / args.phase
    if target.exists(): raise ValueError('Run output exists; inspect/preserve before another run')
    target.mkdir()
    tasks = json.loads((ROOT / (args.phase + '-tasks.json')).read_text(encoding='utf-8'))
    code, health = request('GET', '/health')
    if code != 200 or health['candidates'] != 10000: raise ValueError('Shared service not ready')
    started = time.perf_counter()
    model = load_model()
    import importlib.metadata as metadata
    import torch
    save(target / 'runtime.json', {'model_load_seconds': time.perf_counter()-started,
        'torch': torch.__version__, 'cuda': torch.cuda.is_available(), 'smolagents': metadata.version('smolagents'),
        'transformers': metadata.version('transformers'), 'service_instance': health['instance_id'],
        'llm_runtime_scope': 'existing stage6/shared CUDA env read-only; not the independent stage17 CPU runtime'})
    for index, task in enumerate(tasks):
        for policy in (('fixed', 'llm_agent') if index % 2 == 0 else ('llm_agent', 'fixed')):
            result = run(task, policy, model)
            save(target / f"{task['id']}-{policy}.json", result)
            print(json.dumps({'phase': args.phase, 'index': index, 'policy': policy,
                'completed_protocol': result['completed_protocol'], 'seconds': round(result['seconds'], 3)}), flush=True)


if __name__ == '__main__': main()
