"""Seal the desktop annotation deliverable; mobile acceptance explicitly deferred."""
import contextlib
import importlib.metadata as metadata
import json
from pathlib import Path
import subprocess
import unittest

from gsearch.annotation_store import BlindPool,AnnotationStore,ROOT as DATA
from gsearch.quality_protocol import digest,save
from gsearch.showcase import verify_receipt


def main():
    root=Path('reports/stage26');receipt=root/'final-validation.json'
    if receipt.exists():raise ValueError('Keep the sealed delivery')
    pool=BlindPool();store=AnnotationStore(DATA/'work/annotations.sqlite3',pool)
    http_path=root/'http-validation-667731c9-4ec7-49d0-8ba9-40f858070ad3.json'
    http=json.loads(http_path.read_text(encoding='utf-8'))
    assert http['status']=='passed' and http['count']==32
    browser=json.loads((root/'browser-validation.json').read_text(encoding='utf-8'))
    assert browser['desktop_status']=='passed_core_interactions'
    logs=Path('.cache/stage26/acceptance');logs.mkdir(parents=True,exist_ok=True)
    with (logs/'tests.log').open('w',encoding='utf-8') as stream,contextlib.redirect_stdout(stream),contextlib.redirect_stderr(stream):
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName('scripts.probe_annotation_store'))
    assert result.wasSuccessful() and result.testsRun==9
    old={}
    for stage,groups in {20:('code','vendor','outputs','private_data','docs','report'),
        23:('code','browser_assets','docs','outputs','report','private_validation'),
        24:('code','browser_assets','docs','report','outputs','private_validation')}.items():
        old[str(stage)]=verify_receipt(Path(f'reports/stage{stage}/final-validation.json'),groups)
    previous=json.loads(Path('reports/stage25/validation.json').read_text())
    for name,expected in previous['assets'].items():assert digest(Path(name))==expected
    versions={d.metadata['Name']:d.version for d in metadata.distributions()}
    assert versions==json.loads(Path('reports/stage17/runtime-versions.json').read_text())['installed_versions']
    editor=json.loads((root/'editor-assets.json').read_text())
    for name,expected in editor['files'].items():assert digest(Path(name))==expected
    for p in Path('web/papertrail-v24/dist/vendor').iterdir():assert digest(p)==digest(Path('web/papertrail-v26/dist/vendor')/p.name)
    expected=json.loads(Path('reports/stage13/resource-10000.json').read_text())['model_signature']
    signature=json.loads((DATA/'protocol.json').read_text())['text_signature']
    assert all(expected[k]==v for k,v in signature.items())
    from scripts.annotation_workbench_control import health
    status,value=health();assert status==200 and value['llm_enabled'] is False
    from scripts.manage_stage17_env import environment
    launched=subprocess.run(['cmd.exe','/c',str(Path('annotation-workbench.cmd').resolve()),'start','--no-open'],
        cwd=Path.home(),env=environment(),capture_output=True,text=True,check=True)
    assert json.loads(launched.stdout)['state']=='already_running'
    node=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
    for name in ('app.mjs','label.mjs'):
        subprocess.run([str(node),'--check',str(Path('web/papertrail-v26/dist')/name)],check=True,capture_output=True)
    with store.connect() as db:
        records=db.execute("SELECT kind,COUNT(*) FROM annotation_records WHERE owner NOT LIKE 'verification:%' GROUP BY kind").fetchall()
    current=json.loads((root/'current-verification.json').read_text())
    current.update(status='complete_desktop_annotation_workbench',mobile_visual_acceptance_deferred_by_user=True,
        mobile_visual_acceptance_completed=False,formal_records=dict(records),latest_http_report=str(http_path),latest_http_checks=32,
        service_running=True,service_instance=value['instance_id'])
    save(root/'current-verification.json',current)
    code=['gsearch/annotation_store.py','gsearch/annotation_workbench.py','scripts/annotation_workbench_control.py',
        'scripts/setup_annotation_assets.py','scripts/prepare_annotation_launcher.py','scripts/build_annotation_pool.py',
        'scripts/probe_annotation_store.py','scripts/validate_annotation_http.py','scripts/verify_annotation_delivery.py','annotation-workbench.cmd']
    docs=['docs/ANNOTATION_WORKBENCH.md','web/papertrail-v26/THIRD_PARTY_NOTICES.md']
    report=Path('reports/阶段26_站内需求确认与盲标.md')
    manifest=json.loads((DATA/'manifest.json').read_text())
    pool_files=[DATA/name for name in manifest['immutable_assets']]+[DATA/'manifest.json']
    private=[p for p in (DATA/'verification').rglob('*.json')]+[logs/'tests.log']
    save(receipt,{'status':'complete_desktop_annotation_workbench','url':'http://127.0.0.1:8769/label',
        'queries':9,'pooled_pairs':155,'verified_originals':116,'pool_version':pool.version,
        'tests':result.testsRun,'http_checks':32,'desktop_browser_checks':len(browser['checks']),
        'mobile_visual_acceptance_deferred_by_user':True,'computer_use_stopped_on_url_policy':True,
        'formal_records_at_delivery':dict(records),'automation_created_human_labels':0,'quality_scores_computed':False,
        'old_assets_unchanged':old,'stage25_assets_unchanged':len(previous['assets']),'unchanged_cpu_packages':len(versions),
        'absolute_launcher_from_home_passed':True,'syntax_checks_passed':True,'public_deployment':False,
        'code':{p:digest(Path(p)) for p in code},'browser_assets':{str(p):digest(p) for p in Path('web/papertrail-v26/dist').rglob('*') if p.is_file()},
        'docs':{p:digest(Path(p)) for p in docs},'report':{str(report):digest(report)},
        'outputs':{str(p):digest(p) for p in root.glob('*.json') if p!=receipt},
        'private_pool':{str(p):digest(p) for p in pool_files},'private_validation':{str(p):digest(p) for p in private},
        'mutable_sqlite_and_runtime_excluded':True})
    print(json.dumps({'status':'complete_desktop','tests':result.testsRun,'http_checks':32,'formal_records':dict(records),
        'url':'http://127.0.0.1:8769/label','receipt_sha256':digest(receipt)},ensure_ascii=False))


if __name__=='__main__':main()
