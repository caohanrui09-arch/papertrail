"""Seal personal-search delivery; live visitor DB and runtime state stay mutable."""
import importlib.metadata as metadata
import json
from pathlib import Path
import subprocess
from gsearch.quality_protocol import digest, save
from gsearch.showcase import verify_receipt
from scripts.assemble_model_review import formal_state
from scripts.personal_search_control import health
from scripts.manage_stage17_env import environment

ROOT = Path('reports/stage35')
GROUPS = ('code', 'web', 'docs', 'report', 'outputs', 'private_validation')


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main() -> None:
    receipt = ROOT / 'final-validation.json'
    if receipt.exists():
        print(json.dumps({'verified_existing': True, 'assets': verify_receipt(receipt, GROUPS), 'sha256': digest(receipt)}))
        return
    core = load(ROOT / 'core-http-validation.json')
    personal = load(ROOT / 'personal-http-validation.json')
    numerical = load(ROOT / 'numerical-validation.json')
    reused = load(ROOT / 'reused-tests.json')
    browser = load(ROOT / 'browser-validation.json')
    audit = load(ROOT / 'catalog-adaptation.json')
    assert core['status'] == 'passed' and core['count'] == 43
    assert personal['status'] == 'passed' and personal['count'] == 50 and personal['http_test_preferences_cleaned']
    assert numerical['status'] == 'passed' and len(numerical['two_like_independent_dense_scores']) == 6
    assert reused['status'] == 'passed' and reused['tests'] == 8
    assert browser['status'] == 'passed_personal_feedback_loop' and len(browser['checks']) == 21 and browser['test_preferences_cleaned']
    assert audit['new_count'] == 42 and audit['overlap_ids'] == ['2412.04746'] and not audit['old_preferences_imported']
    assert all(digest(Path(path)) == value for path, value in audit['reused_code'].items())
    screenshots = [Path(path) for path in browser['screenshots']]
    for path in screenshots:
        assert path.suffix == '.jpg' and path.read_bytes().startswith(b'\xff\xd8\xff')
    for path in Path('web/papertrail-v34/dist/vendor').iterdir():
        assert digest(path) == digest(Path('web/papertrail-v35/dist/vendor') / path.name)
    # Reading adaptations and the established visual sheet are reused unchanged.
    for name in ('reading.mjs', 'reading.css', 'styles.css', 'mark.svg'):
        assert digest(Path('web/papertrail-v34/dist') / name) == digest(Path('web/papertrail-v35/dist') / name)
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
        34: ('code', 'web', 'docs', 'report', 'outputs', 'private_validation'),
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
    code = ['gsearch/personal_search_v2.py', 'scripts/personal_search_control.py', 'scripts/audit_personal_v2.py',
            'scripts/validate_personal_search_core.py', 'scripts/validate_personal_search_http.py',
            'scripts/verify_personal_search_delivery.py', 'papertrail-personal.cmd']
    for name in code:
        if name.endswith('.py'):
            compile(Path(name).read_text(encoding='utf-8'), name, 'exec')
    node = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
    for name in ('main.mjs', 'personal.mjs', 'reading.mjs'):
        subprocess.run([str(node), '--check', str(Path('web/papertrail-v35/dist') / name)], check=True, capture_output=True)
    status, value = health()
    assert status == 200 and value['llm_enabled'] is False and value['catalog'] == 42
    launched = subprocess.run(['cmd.exe', '/c', str(Path('papertrail-personal.cmd').resolve()), 'start', '--no-open'],
                              cwd=Path.home(), env=environment(), text=True, capture_output=True, check=True)
    assert json.loads(launched.stdout)['state'] == 'already_running'
    save(ROOT / 'validation.json', {
        'status': 'passed', 'core_http_checks': 43, 'personal_http_checks': 50, 'reused_cpu_tests': 8,
        'independent_vector_scores': 6, 'browser_checks': 21, 'test_preferences_cleaned': True,
        'old_assets_unchanged': old, 'stage25_assets_unchanged': len(previous),
        'stage31_source_files_unchanged': len(sources), 'unchanged_cpu_packages': len(versions),
        'formal_state': state, 'existing_vendor_and_reading_files_unchanged': True,
        'absolute_launcher_from_home': True, 'old_preferences_imported': False,
        'catalog_key': audit['catalog_key'], 'service_instance_at_delivery': value['instance_id'],
        'live_preferences_excluded_from_seal': True, 'public_deployment': False,
    })
    report = Path('reports/阶段35_真实收藏与个人推荐闭环.md')
    docs = [Path('docs/PAPERTRAIL_PERSONAL_V35.md'), Path('web/papertrail-v35/THIRD_PARTY_NOTICES.md')]
    save(receipt, {
        'status': 'complete_local_personal_content_loop', 'url': 'http://127.0.0.1:8777',
        'code': {p: digest(Path(p)) for p in code},
        'web': {str(p): digest(p) for p in Path('web/papertrail-v35/dist').rglob('*') if p.is_file()},
        'docs': {str(p): digest(p) for p in docs}, 'report': {str(report): digest(report)},
        'outputs': {str(p): digest(p) for p in ROOT.glob('*.json') if p != receipt},
        'private_validation': {str(p): digest(p) for p in screenshots},
        'mutable_runtime_and_preferences_excluded': True,
    })
    print(json.dumps({'status': 'sealed', 'assets': verify_receipt(receipt, GROUPS), 'sha256': digest(receipt)}))


if __name__ == '__main__':
    main()
