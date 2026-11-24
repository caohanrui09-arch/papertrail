"""Copy a minimal private, hash-verified replay bundle; no old metadata rewrites."""
import hashlib
import json
from pathlib import Path
import shutil


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    original = Path.cwd().resolve()
    root = (original / '.cache/stage17/replica').resolve()
    if not root.is_relative_to(original / '.cache/stage17') or (root / 'bundle-manifest.json').exists():
        raise ValueError('Expected a new owned stage17 replica; never overwrite completed bundle')
    files = {}
    def copy(source: Path, relative: Path) -> None:
        target = (root / relative).resolve()
        if not target.is_relative_to(root):
            raise ValueError('Bundle destination escaped')
        expected = digest(source)
        if target.exists() and digest(target) != expected:
            raise ValueError('Existing replica file differs: ' + str(relative))
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, target)
        if digest(target) != expected:
            raise ValueError('Copied asset hash differs')
        files[str(relative)] = expected
    for path in sorted(Path('gsearch').rglob('*.py')):
        copy(path, path)
    for folder in ('third_party/recommenders_sar_upstream', 'third_party/arxiv_py_upstream'):
        for path in sorted(Path(folder).rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                copy(path, path)
    selected = ('reports/stage9/upstream-audit.json', 'reports/stage10/upstream-audit.json',
        'reports/stage13/admission-plan.json', 'reports/stage13/resource-10000.json',
        'reports/stage15/locked-before-dev.json', 'data/stage9-recommendation/train.csv',
        'data/stage13-expansion/documents.json', 'data/stage13-expansion/catalog-10000.json')
    for name in selected:
        copy(Path(name), Path(name))
    delivered = json.loads(Path('reports/stage16/delivery-manifest.json').read_text(encoding='utf-8'))
    demo = next(Path(name) for name in delivered['private_assets'] if name.endswith('demo.json'))
    if digest(demo) != delivered['private_assets'][str(demo)]:
        raise ValueError('Original demonstration changed')
    copy(demo, Path('data/relocation-reference/demo.json'))
    rows = json.loads(Path('data/stage13-expansion/documents.json').read_text(encoding='utf-8'))
    responses = {}
    for row in rows:
        receipt = row['provenance']; source = Path(receipt['raw_path'])
        sha = receipt['raw_sha256']
        if len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha) or digest(source) != sha:
            raise ValueError('Original official response differs')
        if sha not in responses:
            relative = Path('.cache/stage13/raw') / (sha + '.body')
            copy(source, relative); responses[sha] = str(relative)
    manifest = {'client_date': '2026-10-28', 'files': files, 'private_local_only': True,
        'documents': len(rows), 'official_source_bodies': len(responses),
        'source_stage16_receipt_sha256': digest(Path('reports/stage16/final-validation.json')),
        'source_stage15_receipt_sha256': digest(Path('reports/stage15/final-validation.json')),
        'relocation': 'All copied bytes unchanged; relocated_demo changes raw_path in memory only',
        'dependency_target': '.cache/stage11/deps is newly installed from pinned hashes, not copied'}
    (root / 'bundle-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'bundle': str(root), 'files': len(files), 'documents': len(rows), 'raw_bodies': len(responses)}), flush=True)


if __name__ == '__main__':
    main()
