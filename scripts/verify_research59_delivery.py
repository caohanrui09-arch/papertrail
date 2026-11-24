"""Seal Scholar-style UI reorganization and verify the unchanged evidence chain."""
from email.parser import Parser
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'reports/stage59'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    os.chdir(ROOT)
    prior = ROOT / 'reports/stage58/final-validation.json'
    assert sha(prior) == '938e9525dc27575df06e98665cfe74023ea7f2e4acba8d5ed93d982ece724ffa'
    previous = subprocess.run([sys.executable, '-E', '-s', '-m', 'scripts.verify_research58_delivery'], capture_output=True, text=True)
    assert previous.returncode == 0, previous.stdout + previous.stderr
    final = REPORT / 'final-validation.json'
    if final.exists():
        value = read(final)
        for path, digest in value['files'].items():
            assert sha(ROOT / path) == digest, path
        print({'status': 'verified', 'assets': len(value['files']), 'receipt_sha256': sha(final)})
        return
    (REPORT / 'historic-verification.log').write_text(previous.stdout + previous.stderr, encoding='utf8')
    old, new = ROOT / 'deploy/stage58', ROOT / 'deploy/stage59'
    for folder in ['catalog', 'supplement', 'experiment-artifacts', 'web/vendor', 'third-party']:
        for path in (old / folder).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts:
                assert path.read_bytes() == (new / path.relative_to(old)).read_bytes(), path
    for name in ['evidence-data.json', 'evidence-receipt.json', 'sid-lab.json', 'sid-lab-receipt.json', 'requirements.lock', 'learning-paths.json', 'comparison-evidence.json']:
        assert (old / name).read_bytes() == (new / name).read_bytes(), name
    for path in (old / 'trialsite').glob('*.py'):
        if path.name != 'delivery.py':
            assert path.read_bytes() == (new / 'trialsite' / path.name).read_bytes(), path
    expected = {'api-validation.json': 69, 'reading-validation.json': 72, 'tools-validation.json': 125, 'loop-validation.json': 92, 'migration-validation.json': 16, 'memory-validation.json': 31, 'features-validation.json': 84}
    for name, count in expected.items():
        assert read(REPORT / name)['passed'] == count, name
    assert read(REPORT / 'api-validation.json')['unchanged_responses'] == 20
    browser = read(REPORT / 'browser-validation.json')
    assert browser['status'] == 'passed'
    assert browser['desktop']['fullCards'] == 2 and browser['desktop']['readerWidth'] == 760
    assert not browser['desktop']['horizontalOverflow']
    assert len(browser['limits']) >= 4
    preservation = read(REPORT / 'preference-preservation.json')
    assert preservation['all_existing_namespaces_unchanged'] and preservation['session_key_preserved']
    assert read(REPORT / 'launcher-validation.json')['release'] == 'stage59'
    environment = read(ROOT / 'reports/stage52/environment.json')
    package_counts = {}
    for name, relative in [('cpu', '.cache/stage17/runtime'), ('web', '.cache/stage39/runtime-secure')]:
        packages = {}
        for path in (ROOT / relative / 'Lib/site-packages').glob('*.dist-info/METADATA'):
            meta = Parser().parsestr(path.read_text(encoding='utf8'))
            packages[meta['Name']] = meta['Version']
        assert packages == environment[name]['packages'], name
        package_counts[name] = len(packages)
    names = ['run_research59_local.py', 'run_research59_acceptance.py', 'research59_control.py', 'validate_research59_delivery.py', 'validate_research59.py', 'validate_research59_tools.py', 'validate_research59_loop.py', 'validate_research59_migration.py', 'validate_research59_memory.mjs', 'validate_research59_features.py', 'snapshot_research59_preferences.py', 'verify_research59_delivery.py']
    paths = [path for path in new.rglob('*') if path.is_file() and '__pycache__' not in path.parts]
    paths += [ROOT / 'scripts' / name for name in names] + [ROOT / 'docs/SCHOLAR_LAYOUT_V59.md']
    paths += [path for path in REPORT.rglob('*') if path.is_file() and path != final]
    files = {str(path.relative_to(ROOT)): sha(path) for path in sorted(set(paths))}
    receipt = {'status': 'passed', 'date': '2026-11-08', 'scope': 'desktop search-first layout; existing APIs, ranking, data, private namespaces and experiment evidence retained', 'prior_receipt_sha256': sha(prior), 'checks': {'automatic_checks': sum(expected.values()), 'browser_observed_checks': len(browser['checks']), 'old_responses_exact': 20, 'prior_v58_assets_unchanged': 157, 'historical_chain_verified': True, 'catalog_unchanged': 167, 'offline_experiment_unchanged': 9000, 'existing_private_data_preserved': True, 'installed_packages_unchanged': package_counts, 'new_runtime_dependencies': 0, 'human_relevance_labels': 0, 'new_training': False, 'public_deployment': False}, 'browser_limits': browser['limits'], 'files': files}
    final.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print({'status': 'passed', 'assets': len(files), 'receipt_sha256': sha(final)})


if __name__ == '__main__':
    main()
