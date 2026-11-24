"""Verify and seal the distinct local studio frontend, without changing old assets."""
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import subprocess
import socket
import urllib.request
import urllib.error
from gsearch.quality_protocol import digest, save
from gsearch.showcase import verify_receipt
from scripts.assemble_model_review import formal_state
from scripts.search_reading_control import health
from scripts.manage_stage17_env import environment

ROOT = Path('reports/stage34')
GROUPS = ('code', 'web', 'docs', 'report', 'outputs', 'private_validation')


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main() -> None:
    receipt = ROOT / 'final-validation.json'
    if receipt.exists():
        print(json.dumps({'verified_existing': True, 'assets': verify_receipt(receipt, GROUPS), 'sha256': digest(receipt)}))
        return
    http = load(ROOT / 'http-validation.json')
    assert http['status'] == 'passed' and http['count'] == 41
    browser = load(ROOT / 'browser-validation.json')
    assert browser['status'] == 'passed_desktop_reading' and len(browser['checks']) == 26
    contrast = load(ROOT / 'contrast-validation.json')
    assert contrast['status'] == 'passed' and contrast['sample_count'] == 47
    assert contrast['minimum_ratio'] >= 4.5
    screenshots = [Path(p) for p in browser['screenshots']]
    assert len(screenshots) == 3
    for image in screenshots:
        assert image.suffix == '.jpg' and image.read_bytes().startswith(b'\xff\xd8\xff')
    for path in Path('web/papertrail-v33/dist/vendor').iterdir():
        assert digest(path) == digest(Path('web/papertrail-v34/dist/vendor') / path.name)
    vendor = load('reports/stage33/vendor-source.json')
    assert vendor['commit'] == '01b81be1df6843ccfe0a71c0699a746bf740dd77' and vendor['version'] == '4.5.0'
    for item in vendor['files']:
        raw = Path(item['path']).read_bytes()
        assert len(raw) == item['bytes'] and hashlib.sha256(raw).hexdigest() == item['sha256']
        assert hashlib.sha1(f'blob {len(raw)}\0'.encode() + raw).hexdigest() == item['git_blob']
    old = {}
    stages = {
        20: ('code', 'vendor', 'outputs', 'private_data', 'docs', 'report'),
        23: ('code', 'browser_assets', 'docs', 'outputs', 'report', 'private_validation'),
        24: ('code', 'browser_assets', 'docs', 'report', 'outputs', 'private_validation'),
        26: ('code', 'browser_assets', 'docs', 'report', 'outputs', 'private_pool', 'private_validation'),
        27: ('code', 'docs', 'report', 'outputs', 'private_review'),
        28: ('code', 'report', 'outputs', 'private_diagnostic'),
        29: ('code', 'docs', 'report', 'outputs', 'private_data', 'raw'),
        30: ('code', 'web', 'docs', 'report', 'outputs', 'private_review'),
        32: ('code', 'web', 'docs', 'report', 'outputs', 'private_validation'),
        33: ('code', 'web', 'docs', 'report', 'outputs', 'private_validation'),
    }
    for stage, groups in stages.items():
        old[str(stage)] = verify_receipt(Path(f'reports/stage{stage}/final-validation.json'), groups)
    previous = load('reports/stage25/validation.json')['assets']
    assert all(digest(Path(p)) == value for p, value in previous.items())
    sources = load('reports/stage31/validation.json')['files']
    assert all(digest(Path(p)) == value for p, value in sources.items())
    versions = {d.metadata['Name']: d.version for d in metadata.distributions()}
    assert versions == load('reports/stage17/runtime-versions.json')['installed_versions']
    state = formal_state()
    baseline = load('data/stage27-model-review/formal-baseline.json')
    assert state == {k: baseline[k] for k in state}
    code = ['gsearch/search_v2_reading.py', 'scripts/search_reading_control.py', 'scripts/reading_ui_fixture.py',
            'scripts/audit_reading_contrast.py', 'scripts/validate_reading_http.py', 'scripts/verify_reading_delivery.py', 'search-reading.cmd']
    for name in code:
        if name.endswith('.py'):
            compile(Path(name).read_text(encoding='utf-8'), name, 'exec')
    node = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
    subprocess.run([str(node), '--check', 'web/papertrail-v34/dist/main.mjs'], check=True, capture_output=True)
    subprocess.run([str(node), '--check', 'web/papertrail-v34/dist/reading.mjs'], check=True, capture_output=True)
    with socket.socket() as probe:
        assert probe.connect_ex(('127.0.0.1', 8776)) != 0
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        opener.open('http://127.0.0.1:8775/_probe/normal', timeout=5)
        raise AssertionError('Fixture leaked to delivery app')
    except urllib.error.HTTPError as error:
        assert error.code == 404
    status, value = health()
    assert status == 200 and value['llm_enabled'] is False and value['catalog'] == 42
    launched = subprocess.run(['cmd.exe', '/c', str(Path('search-reading.cmd').resolve()), 'start', '--no-open'],
                              cwd=Path.home(), env=environment(), text=True, capture_output=True, check=True)
    assert json.loads(launched.stdout)['state'] == 'already_running'
    save(ROOT / 'validation.json', {
        'status': 'passed', 'http_checks': 41, 'browser_checks': 26, 'contrast_samples': 47, 'minimum_sampled_contrast': contrast['minimum_ratio'],
        'old_assets_unchanged': old, 'stage25_assets_unchanged': len(previous),
        'stage31_source_files_unchanged': len(sources), 'unchanged_cpu_packages': len(versions),
        'formal_state': state, 'existing_vendor_files_unchanged': True, 'anime_git_blobs_verified': True,
        'absolute_launcher_from_home': True, 'fixture_stopped': True, 'fixture_control_absent_on_delivery': True, 'fixture_viewport_restored': True,
        'service_instance_at_delivery': value['instance_id'], 'mobile_visual_acceptance_deferred': True,
        'reading_focus_mode_tested': True, 'os_reduced_motion_tested': False, 'public_deployment': False,
    })
    report = Path('reports/阶段34_可读性与连续阅读.md')
    docs = [Path('docs/PAPERTRAIL_READING_V34.md'), Path('web/papertrail-v34/THIRD_PARTY_NOTICES.md')]
    save(receipt, {
        'status': 'complete_local_continuous_reading', 'url': 'http://127.0.0.1:8775',
        'code': {p: digest(Path(p)) for p in code},
        'web': {str(p): digest(p) for p in Path('web/papertrail-v34/dist').rglob('*') if p.is_file()},
        'docs': {str(p): digest(p) for p in docs}, 'report': {str(report): digest(report)},
        'outputs': {str(p): digest(p) for p in ROOT.glob('*.json') if p != receipt},
        'private_validation': {str(p): digest(p) for p in screenshots + [Path(browser['raw_color_samples'])]}, 'mutable_runtime_excluded': True,
    })
    print(json.dumps({'status': 'sealed', 'assets': verify_receipt(receipt, GROUPS), 'sha256': digest(receipt)}))


if __name__ == '__main__':
    main()
