"""Seal visual topic gallery; reuse backend and retain immutable upstream source evidence."""
import importlib.metadata as metadata
import json
from pathlib import Path
import subprocess
from gsearch.quality_protocol import digest, save
from gsearch.showcase import verify_receipt
from scripts.assemble_model_review import formal_state
from scripts.topic_gallery_control import health
from scripts.manage_stage17_env import environment

ROOT = Path('reports/stage37')
GROUPS = ('code','web','docs','report','outputs','private_validation')
RECEIPT_GROUPS = GROUPS + ('reference',)


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main():
    receipt = ROOT / 'final-validation.json'
    if receipt.exists():
        print(json.dumps({'verified_existing':True,'assets':verify_receipt(receipt,RECEIPT_GROUPS),'sha256':digest(receipt)}))
        return
    core, browser, contrast = [load(ROOT / name) for name in ('core-http-validation.json','browser-validation.json','contrast-validation.json')]
    assert core['status'] == browser['status'] == contrast['status'] == 'passed'
    assert core['count'] == 49 and len(browser['checks']) == 15 and not browser['preferences_mutated']
    assert contrast['sample_count'] == 21 and contrast['minimum_ratio'] >= 4.5
    images = [Path(p) for p in browser['screenshots']]
    assert all(p.read_bytes().startswith(b'\xff\xd8\xff') for p in images)
    import hashlib
    sources = load(ROOT / 'source-integrity.json')
    for name, value in sources.items():
        raw = Path('web/papertrail-v37/reference/' + name + '.txt').read_bytes()
        assert hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() == value['git_blob']
        assert hashlib.sha256(raw).hexdigest() == value['sha256']
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
    for filename in ('styles.css','reading.mjs','reading.css','mark.svg','personal.mjs','personal.css','backup.mjs','backup.css'):
        assert digest(Path('web/papertrail-v36/dist')/filename) == digest(Path('web/papertrail-v37/dist')/filename)
    for path in Path('web/papertrail-v36/dist/vendor').iterdir():
        assert digest(path) == digest(Path('web/papertrail-v37/dist/vendor')/path.name)
    code = ['gsearch/topic_gallery.py','scripts/topic_gallery_control.py','scripts/validate_gallery_search_core.py',
            'scripts/audit_gallery_contrast.py','scripts/verify_gallery_delivery.py','papertrail-gallery.cmd']
    for path in code:
        if path.endswith('.py'):
            compile(Path(path).read_text(encoding='utf-8'), path, 'exec')
    node = Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
    for name in ('main.mjs','personal.mjs','backup.mjs','reading.mjs','topics.mjs','spotlight.mjs'):
        subprocess.run([str(node),'--check',str(Path('web/papertrail-v37/dist')/name)],check=True,capture_output=True)
    code_status, health_value = health()
    assert code_status == 200 and health_value['catalog'] == 42 and not health_value['llm_enabled']
    command = subprocess.run(['cmd.exe','/c',str(Path('papertrail-gallery.cmd').resolve()),'start','--no-open'],
                             cwd=Path.home(),env=environment(),capture_output=True,text=True,check=True)
    assert json.loads(command.stdout)['state'] == 'already_running'
    save(ROOT/'validation.json',{'status':'passed','core_http':49,'browser_checks':15,'sampled_color_count':21,
         'minimum_base_color_contrast':contrast['minimum_ratio'],'old_assets_unchanged':old,'unchanged_cpu_packages':len(versions),
         'formal_state':state,'existing_backend_and_ui_modules_unchanged':True,'absolute_launcher_from_home':True,
         'upstream_source_blobs_verified':True,'live_database_excluded':True,
         'service_instance':health_value['instance_id'],'public_deployment':False,'quality_gain_claimed':False})
    report = Path('reports/阶段37_主题探索视觉重构.md')
    docs = [Path('docs/PAPERTRAIL_GALLERY_V37.md'),Path('web/papertrail-v37/THIRD_PARTY_NOTICES.md')]
    save(receipt,{'status':'complete_local_topic_gallery','url':'http://127.0.0.1:8779/',
         'code':{p:digest(Path(p)) for p in code},
         'web':{str(p):digest(p) for p in Path('web/papertrail-v37/dist').rglob('*') if p.is_file()},
         'docs':{str(p):digest(p) for p in docs},'reference':{str(p):digest(p) for p in Path('web/papertrail-v37/reference').glob('*')},'report':{str(report):digest(report)},
         'outputs':{str(p):digest(p) for p in ROOT.glob('*.json') if p != receipt},
         'private_validation':{str(p):digest(p) for p in images},'mutable_database_excluded':True})
    print(json.dumps({'status':'sealed','assets':verify_receipt(receipt,RECEIPT_GROUPS),'sha256':digest(receipt)}))


if __name__ == '__main__':
    main()
