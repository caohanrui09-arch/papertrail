"""Replay frozen recommendation tools from a hash-verified relocated private bundle.

The only data adaptation is an in-memory raw-response path map. Original JSON,
training data, source bodies and frozen model/scorer implementations stay intact.
"""
import argparse
import hashlib
import json
from pathlib import Path
import site
import sys


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_bundle(folder: Path) -> dict:
    root = folder.resolve()
    manifest = json.loads((root / 'bundle-manifest.json').read_text(encoding='utf-8'))
    for relative, expected in manifest['files'].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file() or digest(path) != expected:
            raise ValueError('Relocated asset missing, escaped or changed: ' + relative)
    return manifest


def relocated_records(rows: list[dict], root: Path) -> list[dict]:
    result = []
    cache = (root / '.cache/stage13/raw').resolve()
    for original in rows:
        row = dict(original); provenance = dict(row['provenance'])
        sha = provenance['raw_sha256']
        if len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
            raise ValueError('Invalid official response digest')
        path = cache / (sha + '.body')
        if not path.is_file() or digest(path) != sha:
            raise ValueError('Relocated official response changed')
        provenance['raw_path'] = str(path)
        row['provenance'] = provenance
        result.append(row)
    return result


def runtime_origins(root: Path) -> dict:
    import numpy
    import scipy
    import pandas
    import torch
    import transformers
    import sklearn
    import smolagents
    isolation = root.parent.resolve()
    if not Path(sys.prefix).resolve().is_relative_to(isolation / 'runtime'):
        raise ValueError('Expected independently created stage17 virtual environment')
    if not Path(sys.base_prefix).resolve().is_relative_to(isolation / 'python') or site.ENABLE_USER_SITE:
        raise ValueError('Unexpected base Python or enabled user site')
    allowed = (root.resolve(), (isolation / 'runtime').resolve(), (isolation / 'python').resolve())
    origins = {}
    for name, module in sys.modules.copy().items():
        source = getattr(module, '__file__', None)
        if source and not source.startswith('<'):
            path = Path(source).resolve()
            if not any(path.is_relative_to(base) for base in allowed):
                raise ValueError('Imported module escaped isolated roots: ' + name)
    for entry in sys.path:
        path = Path(entry or '.').resolve()
        if not any(path.is_relative_to(base) for base in allowed):
            raise ValueError('sys.path escaped independent runtime/bundle roots')
    for module in (numpy, scipy, pandas, torch, transformers, sklearn, smolagents):
        origins[module.__name__] = {'version': module.__version__, 'origin': str(Path(module.__file__).resolve().relative_to(isolation))}
    if torch.version.cuda is not None:
        raise ValueError('Expected standalone CPU Torch, not inherited CUDA Torch')
    return {'python': sys.version.split()[0], 'base_inside_managed_install': True, 'user_site_enabled': site.ENABLE_USER_SITE,
        'all_imported_file_origins_inside_isolation': True, 'packages': origins, 'cuda_runtime': torch.version.cuda}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--output', type=Path, required=True)
    args = p.parse_args(); root = Path.cwd().resolve(); manifest = verify_bundle(root)
    output = args.output.resolve()
    if not output.is_relative_to(root / 'data') or output.exists():
        raise ValueError('Use a new private data/ output inside this relocated bundle')
    from .content_recommendation import sklearn_runtime
    sklearn_runtime()
    from .expansion_recommendation import ExpansionRecommender, signature
    from .cold_fusion import ColdAwareRecommender
    from .showcase import run_tools, verify_demo
    import pandas as pd
    from threadpoolctl import threadpool_limits
    original_rows = json.loads(Path('data/stage13-expansion/documents.json').read_text(encoding='utf-8'))
    records = relocated_records(original_rows, root)
    train = pd.read_csv('data/stage9-recommendation/train.csv', dtype={'user_id': str, 'arxiv_id': str})
    cutoff = json.loads(Path('reports/stage13/admission-plan.json').read_text(encoding='utf-8'))['cutoff']
    expected = json.loads(Path('reports/stage13/resource-10000.json').read_text(encoding='utf-8'))['model_signature']
    reference = json.loads(Path('data/relocation-reference/demo.json').read_text(encoding='utf-8'))
    alpha = json.loads(Path('reports/stage15/locked-before-dev.json').read_text(encoding='utf-8'))['diagnostic_alpha']
    with threadpool_limits(limits=1):
        model = ColdAwareRecommender(ExpansionRecommender(train, records, cutoff))
        if signature(model) != expected:
            raise ValueError('Standalone CPU fit differs from frozen model signature')
        # Reparse and replay the old demonstration first, then execute genuine tools anew.
        verified = verify_demo(model, reference, alpha)
        actual = run_tools(model, reference['user_id'], reference['as_of'], alpha, 3)
        if actual != reference['methods'] or signature(model) != expected:
            raise ValueError('Relocated native tools changed output or fitted state')
        origins = runtime_origins(root)
    result = {'status': 'passed', 'scope': 'same physical Windows machine; fresh managed CPython, fresh CPU wheels and relocated private bundle',
        'physical_second_machine_tested': False, 'bundle_manifest_sha256': digest(root / 'bundle-manifest.json'),
        'verified_bundle_assets': len(manifest['files']), 'official_documents': len(records),
        'raw_path_mapping': 'in memory only; original metadata bytes unchanged',
        'source_raw_bodies': len({row['provenance']['raw_sha256'] for row in records}),
        'frozen_model_signature_exact': True, 'three_method_traces_exact': True, 'originals_reparsed': verified,
        'runtime_isolation': origins, 'fresh_network_needed_for_replay': False}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': 'passed', 'documents': len(records), 'originals': verified,
        'output': str(output.relative_to(root)), 'isolated_module_origins': True}), flush=True)


if __name__ == '__main__':
    main()
