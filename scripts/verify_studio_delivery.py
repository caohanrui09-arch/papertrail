"""Verify and seal the distinct local studio frontend, without changing old assets."""
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import subprocess
from gsearch.quality_protocol import digest, save
from gsearch.showcase import verify_receipt
from scripts.assemble_model_review import formal_state
from scripts.search_studio_control import health
from scripts.manage_stage17_env import environment

ROOT = Path('reports/stage33')
GROUPS = ('code', 'web', 'docs', 'report', 'outputs', 'private_validation')


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main() -> None:
    receipt = ROOT / 'final-validation.json'
    if receipt.exists():
        print(json.dumps({'verified_existing': True, 'assets': verify_receipt(receipt, GROUPS), 'sha256': digest(receipt)}))
        return
    http = load(ROOT / 'http-validation.json')
    assert http['status'] == 'passed' and http['count'] == 39
    browser = load(ROOT / 'browser-validation.json')
    assert browser['status'] == 'passed_desktop_interactions' and len(browser['checks']) == 24
    assert browser['default_viewport_restored'] and browser['ui_motion_off_tested']
    screenshots = [Path(p) for p in browser['screenshots']]
    assert len(screenshots) == 3
    for image in screenshots:
        assert image.suffix == '.jpg' and image.read_bytes().startswith(b'\xff\xd8\xff')
    for path in Path('web/papertrail-v32/dist/vendor').iterdir():
        assert digest(path) == digest(Path('web/papertrail-v33/dist/vendor') / path.name)
    vendor = load(ROOT / 'vendor-source.json')
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
    code = ['gsearch/search_v2_studio.py', 'scripts/search_studio_control.py', 'scripts/prepare_visual_web.py',
            'scripts/validate_studio_http.py', 'scripts/verify_studio_delivery.py', 'search-studio.cmd']
    for name in code:
        if name.endswith('.py'):
            compile(Path(name).read_text(encoding='utf-8'), name, 'exec')
    node = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
    subprocess.run([str(node), '--check', 'web/papertrail-v33/dist/main.mjs'], check=True, capture_output=True)
    status, value = health()
    assert status == 200 and value['llm_enabled'] is False and value['catalog'] == 42
    launched = subprocess.run(['cmd.exe', '/c', str(Path('search-studio.cmd').resolve()), 'start', '--no-open'],
                              cwd=Path.home(), env=environment(), text=True, capture_output=True, check=True)
    assert json.loads(launched.stdout)['state'] == 'already_running'
    save(ROOT / 'validation.json', {
        'status': 'passed', 'http_checks': 39, 'browser_checks': 24,
        'old_assets_unchanged': old, 'stage25_assets_unchanged': len(previous),
        'stage31_source_files_unchanged': len(sources), 'unchanged_cpu_packages': len(versions),
        'formal_state': state, 'existing_vendor_files_unchanged': True, 'anime_git_blobs_verified': True,
        'absolute_launcher_from_home': True, 'default_viewport_restored': True,
        'service_instance_at_delivery': value['instance_id'], 'mobile_visual_acceptance_deferred': True,
        'ui_motion_off_tested': True, 'os_reduced_motion_tested': False, 'public_deployment': False,
    })
    report = Path('reports/阶段33_论文发现工作室视觉重做.md')
    docs = [Path('docs/PAPERTRAIL_STUDIO_V33.md'), Path('web/papertrail-v33/THIRD_PARTY_NOTICES.md')]
    save(receipt, {
        'status': 'complete_local_visual_rebuild', 'url': 'http://127.0.0.1:8773',
        'code': {p: digest(Path(p)) for p in code},
        'web': {str(p): digest(p) for p in Path('web/papertrail-v33/dist').rglob('*') if p.is_file()},
        'docs': {str(p): digest(p) for p in docs}, 'report': {str(report): digest(report)},
        'outputs': {str(p): digest(p) for p in ROOT.glob('*.json') if p != receipt},
        'private_validation': {str(p): digest(p) for p in screenshots}, 'mutable_runtime_excluded': True,
    })
    print(json.dumps({'status': 'sealed', 'assets': verify_receipt(receipt, GROUPS), 'sha256': digest(receipt)}))


if __name__ == '__main__':
    main()
