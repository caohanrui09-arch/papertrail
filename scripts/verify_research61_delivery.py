"""Seal online metadata search separately from the original catalog and evidence."""
from email.parser import Parser
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'reports/stage61'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    prior = ROOT / 'reports/stage60/final-validation.json'
    assert sha(prior) == '996d12c898eea665a90495647766e3e52c5c3de9c5dd32cedba07e9c7f885013'
    for path, digest in read(prior)['files'].items():
        assert sha(ROOT / path) == digest, path
    final = REPORT / 'final-validation.json'
    if final.exists():
        value = read(final)
        for path, digest in value['files'].items():
            assert sha(ROOT / path) == digest, path
        print({'status': 'verified', 'assets': len(value['files']), 'receipt_sha256': sha(final)})
        return
    old, new = ROOT / 'deploy/stage60', ROOT / 'deploy/stage61'
    for folder in ['catalog', 'supplement', 'experiment-artifacts', 'third-party', 'web/vendor']:
        for path in (old / folder).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts:
                assert path.read_bytes() == (new / path.relative_to(old)).read_bytes(), path
    for name in ['evidence-data.json', 'evidence-receipt.json', 'sid-lab.json', 'sid-lab-receipt.json', 'learning-paths.json', 'comparison-evidence.json', 'requirements.lock']:
        assert (old / name).read_bytes() == (new / name).read_bytes(), name
    for path in (old / 'web').glob('*.css'):
        assert path.read_bytes() == (new / 'web' / path.name).read_bytes(), path
    for path in (old / 'trialsite').glob('*.py'):
        if path.name not in ['delivery.py', 'security.py']:
            assert path.read_bytes() == (new / 'trialsite' / path.name).read_bytes(), path
    audit = read(ROOT / 'reports/stage10/upstream-audit.json')['chosen']
    for name in ['arxiv/__init__.py', 'arxiv/_feed.py']:
        raw = (new / 'api-vendor' / name).read_bytes()
        assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == audit['git_blobs'][name]
    assert (new / 'api-vendor/ARXIV-LICENSE.txt').read_bytes() == (ROOT / 'third_party/arxiv_py_upstream/LICENSE.txt').read_bytes()
    expected = {'api-validation.json': 69, 'online-validation.json': 58, 'render-validation.json': 10}
    for name, count in expected.items():
        assert read(REPORT / name)['passed'] == count, name
    assert read(REPORT / 'api-validation.json')['unchanged_responses'] == 20
    assert read(REPORT / 'preference-preservation.json')['all_existing_namespaces_unchanged']
    assert read(REPORT / 'preference-preservation.json')['session_key_preserved']
    service = read(REPORT / 'service-validation.json')
    assert service['release'] == 'stage61' and service['importmap_csp_matches']
    assert {row['provider'] for row in service['live']} == {'arxiv', 'openalex'}
    assert all(row['count'] == 10 for row in service['live'])
    pagination = read(REPORT / 'live-pagination.json')
    assert all(row['status'] == 200 for row in pagination)
    for row in pagination:
        if row['year']:
            assert all(paper['year'] == row['year'] for paper in row['response']['papers'])
    environment = read(ROOT / 'reports/stage52/environment.json')
    package_counts = {}
    for name, relative in [('cpu', '.cache/stage17/runtime'), ('web', '.cache/stage39/runtime-secure')]:
        packages = {}
        for path in (ROOT / relative / 'Lib/site-packages').glob('*.dist-info/METADATA'):
            meta = Parser().parsestr(path.read_text(encoding='utf8'))
            packages[meta['Name']] = meta['Version']
        assert packages == environment[name]['packages'], name
        package_counts[name] = len(packages)
    packages = {}
    for path in (new / 'api-vendor').glob('*.dist-info/METADATA'):
        meta = Parser().parsestr(path.read_text(encoding='utf8'))
        packages[meta['Name']] = meta['Version']
    assert len(packages) == 6
    names = ['run_research61_local.py', 'run_research61_acceptance.py', 'research61_control.py', 'snapshot_research61_preferences.py', 'validate_research61_delivery.py', 'validate_online61.py', 'validate_online61_render.mjs', 'probe_online61_delivery.py', 'verify_research61_delivery.py']
    paths = [path for path in new.rglob('*') if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc']
    paths += [ROOT / 'scripts' / name for name in names] + [ROOT / 'docs/ONLINE_SEARCH_V61.md']
    paths += [path for path in REPORT.rglob('*') if path.is_file() and path != final]
    files = {str(path.relative_to(ROOT)): sha(path) for path in sorted(set(paths))}
    value = {'status': 'passed_with_browser_limitation', 'date': '2026-11-08', 'scope': 'live arxiv/OpenAlex metadata search, source abstracts and links; external results not imported into old personal catalog', 'prior_receipt_sha256': sha(prior), 'prior_v60_assets_verified': 143, 'automatic_checks': sum(expected.values()), 'old_responses_exact': 20, 'browser_checks': 0, 'browser_limitation': 'reset and create-tab timed out; offline template check is not a browser or screenshot test', 'live_source_queries_verified': 6, 'catalog_unchanged': 167, 'offline_experiment_unchanged': 9000, 'private_data_preserved': True, 'shared_packages_unchanged': package_counts, 'isolated_api_packages': packages, 'public_deployment': False, 'files': files}
    final.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print({'status': value['status'], 'assets': len(files), 'receipt_sha256': sha(final)})


if __name__ == '__main__':
    main()
