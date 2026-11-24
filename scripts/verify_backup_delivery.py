"""Seal backup delivery; live preference database stays deliberately mutable."""
import importlib.metadata as metadata
import json
from pathlib import Path
import subprocess
from gsearch.quality_protocol import digest, save
from gsearch.showcase import verify_receipt
from scripts.assemble_model_review import formal_state
from scripts.preference_backup_control import health
from scripts.manage_stage17_env import environment

ROOT = Path('reports/stage36')
GROUPS = ('code','web','docs','report','outputs','private_validation')


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main():
    receipt = ROOT / 'final-validation.json'
    if receipt.exists():
        print(json.dumps({'verified_existing':True,'assets':verify_receipt(receipt,GROUPS),'sha256':digest(receipt)}))
        return
    http, core, atomic, browser = [load(ROOT / name) for name in ('backup-http-validation.json','core-http-validation.json','atomicity-validation.json','browser-validation.json')]
    assert http['status'] == core['status'] == atomic['status'] == browser['status'] == 'passed'
    assert http['http_count'] == 83 and http['concurrent_statuses'] == [200,409] and http['test_spaces_cleaned']
    assert core['count'] == 45 and len(browser['checks']) == 20 and browser['test_preferences_cleaned']
    assert atomic['forced_second_insert_failure_rolled_back_first'] and atomic['revision_rolled_back']
    images = [Path(p) for p in browser['screenshots']]
    assert all(p.read_bytes().startswith(b'\xff\xd8\xff') for p in images)
    old = {}
    stages = {
        20: ('code','vendor','outputs','private_data','docs','report'),
        23: ('code','browser_assets','docs','outputs','report','private_validation'),
        24: ('code','browser_assets','docs','report','outputs','private_validation'),
        26: ('code','browser_assets','docs','report','outputs','private_pool','private_validation'),
        27: ('code','docs','report','outputs','private_review'),
        28: ('code','report','outputs','private_diagnostic'),
        29: ('code','docs','report','outputs','private_data','raw'),
        30: ('code','web','docs','report','outputs','private_review'),
    }
    stages.update({stage:GROUPS for stage in (32,33,34,35)})
    for stage, groups in stages.items():
        old[str(stage)] = verify_receipt(Path(f'reports/stage{stage}/final-validation.json'),groups)
    for stage, group in ((25,'assets'),(31,'files')):
        assets = load(f'reports/stage{stage}/validation.json')[group]
        assert all(digest(Path(p)) == value for p,value in assets.items())
        old[str(stage)] = len(assets)
    versions = {d.metadata['Name']:d.version for d in metadata.distributions()}
    assert versions == load('reports/stage17/runtime-versions.json')['installed_versions']
    state, baseline = formal_state(), load('data/stage27-model-review/formal-baseline.json')
    assert state == {key:baseline[key] for key in state}
    for filename in ('styles.css','reading.mjs','reading.css','mark.svg'):
        assert digest(Path('web/papertrail-v35/dist')/filename) == digest(Path('web/papertrail-v36/dist')/filename)
    for path in Path('web/papertrail-v35/dist/vendor').iterdir():
        assert digest(path) == digest(Path('web/papertrail-v36/dist/vendor')/path.name)
    code = ['gsearch/preference_backup.py','scripts/preference_backup_control.py','scripts/validate_preference_backup.py',
            'scripts/validate_backup_search_core.py','scripts/probe_backup_atomicity.py','scripts/verify_backup_delivery.py','papertrail-backup.cmd']
    for path in code:
        if path.endswith('.py'):
            compile(Path(path).read_text(encoding='utf-8'), path, 'exec')
    node = Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
    for name in ('main.mjs','personal.mjs','backup.mjs','reading.mjs'):
        subprocess.run([str(node),'--check',str(Path('web/papertrail-v36/dist')/name)],check=True,capture_output=True)
    code_status, health_value = health()
    assert code_status == 200 and health_value['catalog'] == 42 and not health_value['llm_enabled']
    command = subprocess.run(['cmd.exe','/c',str(Path('papertrail-backup.cmd').resolve()),'start','--no-open'],
                             cwd=Path.home(),env=environment(),capture_output=True,text=True,check=True)
    assert json.loads(command.stdout)['state'] == 'already_running'
    save(ROOT/'validation.json',{'status':'passed','backup_http':83,'core_http':45,'browser_checks':20,
         'atomic_rollback_verified':True,'old_assets_unchanged':old,'unchanged_cpu_packages':len(versions),
         'formal_state':state,'vendor_and_reading_unchanged':True,'absolute_launcher_from_home':True,
         'existing_v35_live_database_and_cookie_reused':True,'live_database_excluded':True,
         'service_instance':health_value['instance_id'],'public_deployment':False,'quality_gain_claimed':False})
    report = Path('reports/阶段36_收藏导出导入.md')
    docs = [Path('docs/PAPERTRAIL_BACKUP_V36.md'),Path('web/papertrail-v36/THIRD_PARTY_NOTICES.md')]
    save(receipt,{'status':'complete_local_preference_backup','url':'http://127.0.0.1:8778/',
         'code':{p:digest(Path(p)) for p in code},
         'web':{str(p):digest(p) for p in Path('web/papertrail-v36/dist').rglob('*') if p.is_file()},
         'docs':{str(p):digest(p) for p in docs},'report':{str(report):digest(report)},
         'outputs':{str(p):digest(p) for p in ROOT.glob('*.json') if p != receipt},
         'private_validation':{str(p):digest(p) for p in images},'mutable_database_excluded':True})
    print(json.dumps({'status':'sealed','assets':verify_receipt(receipt,GROUPS),'sha256':digest(receipt)}))


if __name__ == '__main__':
    main()
