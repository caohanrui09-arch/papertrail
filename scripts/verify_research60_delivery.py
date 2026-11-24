"""Seal the style correction without claiming an unavailable browser check."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'reports/stage60'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    prior = ROOT / 'reports/stage59/final-validation.json'
    assert sha(prior) == '1117d4bf5725e11018658a1aec5bc9c4bb4fa738c8b277f3b1ff10e967dd7c57'
    for path, digest in read(prior)['files'].items():
        assert sha(ROOT / path) == digest, path
    final = REPORT / 'final-validation.json'
    if final.exists():
        value = read(final)
        for path, digest in value['files'].items():
            assert sha(ROOT / path) == digest, path
        print({'status': 'verified', 'assets': len(value['files']), 'receipt_sha256': sha(final)})
        return
    old, new = ROOT / 'deploy/stage58', ROOT / 'deploy/stage60'
    for folder in ['catalog', 'supplement', 'experiment-artifacts', 'third-party', 'web/vendor']:
        for path in (old / folder).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts:
                assert path.read_bytes() == (new / path.relative_to(old)).read_bytes(), path
    for path in (old / 'web').glob('*.css'):
        assert path.read_bytes() == (new / 'web' / path.name).read_bytes(), path
    for path in (old / 'trialsite').glob('*.py'):
        if path.name != 'delivery.py':
            assert path.read_bytes() == (new / 'trialsite' / path.name).read_bytes(), path
    assert read(REPORT / 'api-validation.json')['passed'] == 69
    assert read(REPORT / 'api-validation.json')['unchanged_responses'] == 20
    assert read(REPORT / 'memory-validation.json')['passed'] == 29
    assert read(REPORT / 'preference-preservation.json')['all_existing_namespaces_unchanged']
    assert read(REPORT / 'service-validation.json')['release'] == 'stage60'
    names = ['run_research60_local.py', 'run_research60_acceptance.py', 'research60_control.py', 'snapshot_research60_preferences.py', 'validate_research60_delivery.py', 'validate_research60_memory.mjs', 'verify_research60_delivery.py']
    paths = [path for path in new.rglob('*') if path.is_file() and '__pycache__' not in path.parts]
    paths += [ROOT / 'scripts' / name for name in names] + [ROOT / 'docs/ORIGINAL_STYLE_V60.md']
    paths += [path for path in REPORT.rglob('*') if path.is_file() and path != final]
    files = {str(path.relative_to(ROOT)): sha(path) for path in sorted(set(paths))}
    value = {'status': 'passed_with_browser_limitation', 'date': '2026-11-08', 'scope': 'restore stage58 visual baseline and improve information hierarchy', 'prior_receipt_sha256': sha(prior), 'prior_v59_assets_verified': 158, 'automatic_checks': 98, 'old_responses_exact': 20, 'browser_checks': 0, 'browser_limitation': 'CUA state and selected-browser recovery timed out; no current screenshot or DOM-flow claim', 'catalog': 167, 'offline_experiment': 9000, 'private_data_preserved': True, 'files': files}
    final.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print({'status': value['status'], 'assets': len(files), 'receipt_sha256': sha(final)})


if __name__ == '__main__':
    main()
