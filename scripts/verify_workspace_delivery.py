"""Seal original preview and reading workspace; preserve frozen history and live preference space."""
import importlib.metadata as metadata
import json
from pathlib import Path
import subprocess
from gsearch.quality_protocol import digest, save
from gsearch.showcase import verify_receipt
from scripts.assemble_model_review import formal_state
from scripts.paper_workspace_control import health
from scripts.manage_stage17_env import environment

ROOT = Path('reports/stage38')
GROUPS = ('code','web','docs','report','outputs','private_validation')
RECEIPT_GROUPS = GROUPS


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main():
    receipt = ROOT / 'final-validation.json'
    if receipt.exists():
        print(json.dumps({'verified_existing':True,'assets':verify_receipt(receipt,RECEIPT_GROUPS),'sha256':digest(receipt)}))
        return
    core, browser, contrast, preview, highlight = [load(ROOT / name) for name in ('core-http-validation.json','browser-validation.json','contrast-validation.json','preview-validation.json','highlight-validation.json')]
    assert all(v['status']=='passed' for v in (core,browser,contrast,preview,highlight))
    assert core['count']==53 and len(browser['checks'])==18 and browser['test_preferences_cleaned']
    assert contrast['sample_count']==26 and contrast['minimum_ratio']>=4.5
    assert preview['preview_count']==42 and len(preview['unchanged_search_responses'])==18
    assert highlight['cases']==8 and highlight['text_preserved']
    images=[Path(p) for p in browser['screenshots']]
    assert all(p.read_bytes().startswith(b'\xff\xd8\xff') for p in images)
    upstream=load(ROOT/'highlight-source.json')
    assert upstream['version']=='2.0.0' and upstream['gitHead']=='86979e99cb6588b1cecdaaf332ae091dcad3e726'
    assert all(digest(Path(p))==value for p,value in upstream['files'].items())
    assert load('.cache/stage38/fixture/process.json')['state']=='stopped'
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
    stages.update({stage:GROUPS for stage in (32,33,34,35,36)})
    stages[37]=GROUPS+('reference',)
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
    for filename in ('styles.css','reading.mjs','reading.css','mark.svg','personal.mjs','personal.css','backup.mjs','backup.css','topics.mjs','topics.css','spotlight.mjs','spotlight.css'):
        assert digest(Path('web/papertrail-v37/dist')/filename)==digest(Path('web/papertrail-v38/dist')/filename)
    for path in Path('web/papertrail-v37/dist/vendor').iterdir():
        assert digest(path)==digest(Path('web/papertrail-v38/dist/vendor')/path.name)
    code=['gsearch/paper_workspace.py','scripts/paper_workspace_control.py','scripts/validate_workspace_core.py',
          'scripts/validate_workspace_previews.py','scripts/probe_workspace_highlight.mjs','scripts/audit_workspace_contrast.py',
          'scripts/workspace_preview_fixture.py','scripts/verify_workspace_delivery.py','papertrail-workspace.cmd']
    for path in code:
        if path.endswith('.py'):
            compile(Path(path).read_text(encoding='utf-8'), path, 'exec')
    node = Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
    for name in ('main.mjs','papers.mjs','highlight.mjs','reading.mjs'):
        subprocess.run([str(node),'--check',str(Path('web/papertrail-v38/dist')/name)],check=True,capture_output=True)
    code_status, health_value = health()
    assert code_status == 200 and health_value['catalog'] == 42 and not health_value['llm_enabled']
    command = subprocess.run(['cmd.exe','/c',str(Path('papertrail-workspace.cmd').resolve()),'start','--no-open'],
                             cwd=Path.home(),env=environment(),capture_output=True,text=True,check=True)
    assert json.loads(command.stdout)['state'] == 'already_running'
    save(ROOT/'validation.json',{'status':'passed','core_http':53,'preview_identity_checks':42,'unchanged_search_responses':18,
         'highlight_boundary_cases':8,'browser_checks':18,'sampled_color_count':26,'minimum_contrast':contrast['minimum_ratio'],
         'old_assets_unchanged':old,'unchanged_cpu_packages':len(versions),'formal_state':state,
         'homepage_and_reading_and_preferences_modules_unchanged':True,'absolute_launcher_from_home':True,
         'live_database_excluded':True,'test_preferences_cleaned':True,'fixture_stopped':True,
         'service_instance':health_value['instance_id'],'public_deployment':False,'quality_gain_claimed':False})
    report = Path('reports/阶段38_论文判断与工作台统一.md')
    docs = [Path('docs/PAPERTRAIL_WORKSPACE_V38.md'),Path('web/papertrail-v38/THIRD_PARTY_NOTICES.md')]
    save(receipt,{'status':'complete_original_preview_workspace','url':'http://127.0.0.1:8780/',
         'code':{p:digest(Path(p)) for p in code},
         'web':{str(p):digest(p) for p in Path('web/papertrail-v38/dist').rglob('*') if p.is_file()},
         'docs':{str(p):digest(p) for p in docs},'report':{str(report):digest(report)},
         'outputs':{str(p):digest(p) for p in ROOT.glob('*.json') if p != receipt},
         'private_validation':{str(p):digest(p) for p in images},'mutable_database_excluded':True})
    print(json.dumps({'status':'sealed','assets':verify_receipt(receipt,RECEIPT_GROUPS),'sha256':digest(receipt)}))


if __name__ == '__main__':
    main()
