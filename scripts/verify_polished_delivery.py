"""Seal the separate UI version; preserve prior receipts and mutable runtime."""
import importlib.metadata as metadata
import json
from pathlib import Path
import socket
import subprocess
import urllib.error
import urllib.request
from gsearch.quality_protocol import digest, save
from gsearch.showcase import verify_receipt
from scripts.assemble_model_review import formal_state
from scripts.search_v2_polished_control import health
from scripts.manage_stage17_env import environment

ROOT = Path('reports/stage32')
GROUPS = ('code', 'web', 'docs', 'report', 'outputs', 'private_validation')


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main():
    receipt = ROOT / 'final-validation.json'
    if receipt.exists():
        print(json.dumps({'verified_existing': True, 'assets': verify_receipt(receipt, GROUPS), 'sha256': digest(receipt)}))
        return
    http = load(ROOT / 'http-validation.json')
    assert http['status'] == 'passed' and http['count'] == 37
    browser = load(ROOT / 'browser-validation.json')
    assert browser['status'] == 'passed_desktop_interactions' and len(browser['checks']) == 22
    assert browser['reduced_motion_os_or_emulation_tested'] is False
    screenshot = Path(browser['screenshot'])
    assert screenshot.suffix == '.jpg' and screenshot.read_bytes().startswith(b'\xff\xd8\xff')
    for path in Path('web/papertrail-v32/dist/vendor').iterdir():
        assert digest(path) == digest(Path('web/papertrail-v30/dist/vendor') / path.name)
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
    code = ['gsearch/search_v2_polished.py', 'scripts/search_v2_polished_control.py',
            'scripts/validate_polished_http.py', 'scripts/polished_ui_fixture.py',
            'scripts/verify_polished_delivery.py', 'search-v2-polished.cmd']
    for name in code:
        if name.endswith('.py'):
            compile(Path(name).read_text(encoding='utf-8'), name, 'exec')
    node = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
    subprocess.run([str(node), '--check', 'web/papertrail-v32/dist/main.mjs'], check=True, capture_output=True)
    status, value = health()
    assert status == 200 and value['llm_enabled'] is False and value['catalog'] == 42
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        opener.open('http://127.0.0.1:8771/_probe/normal', timeout=5)
        raise AssertionError('Fixture unexpectedly exposed on delivery port')
    except urllib.error.HTTPError as error:
        assert error.code == 404
    with socket.socket() as probe:
        assert probe.connect_ex(('127.0.0.1', 8772)) != 0
    launched = subprocess.run(['cmd.exe', '/c', str(Path('search-v2-polished.cmd').resolve()), 'start', '--no-open'],
                              cwd=Path.home(), env=environment(), text=True, capture_output=True, check=True)
    assert json.loads(launched.stdout)['state'] == 'already_running'
    save(ROOT / 'validation.json', {
        'status': 'passed', 'http_checks': 37, 'browser_checks': 22,
        'old_assets_unchanged': old, 'stage25_assets_unchanged': len(previous),
        'stage31_source_files_unchanged': len(sources), 'unchanged_cpu_packages': len(versions),
        'formal_state': state, 'vendor_files_unchanged': True, 'absolute_launcher_from_home': True,
        'fixture_stopped': True, 'fixture_absent_on_delivery_port': True,
        'service_instance_at_delivery': value['instance_id'], 'mobile_visual_acceptance_deferred': True,
        'reduced_motion_verified_by_parsed_rules_only': True, 'public_deployment': False,
    })
    report = Path('reports/阶段32_研究工作台交互精修.md')
    docs = [Path('docs/PAPERTRAIL_INTERACTION_V32.md'), Path('web/papertrail-v32/THIRD_PARTY_NOTICES.md')]
    save(receipt, {
        'status': 'complete_local_interaction_polish', 'url': 'http://127.0.0.1:8771',
        'code': {p: digest(Path(p)) for p in code},
        'web': {str(p): digest(p) for p in Path('web/papertrail-v32/dist').rglob('*') if p.is_file()},
        'docs': {str(p): digest(p) for p in docs}, 'report': {str(report): digest(report)},
        'outputs': {str(p): digest(p) for p in ROOT.glob('*.json') if p != receipt},
        'private_validation': {str(screenshot): digest(screenshot)}, 'mutable_runtime_excluded': True,
    })
    print(json.dumps({'status': 'sealed', 'assets': verify_receipt(receipt, GROUPS), 'sha256': digest(receipt)}))


if __name__ == '__main__':
    main()
