"""Seal v24 independently, with actual tests and unchanged legacy assets."""
import contextlib
import importlib.metadata as metadata
import json
from pathlib import Path
import subprocess
import unittest
from gsearch.quality_protocol import digest,save
from gsearch.showcase import verify_receipt


def main():
    root=Path('reports/stage24')
    final=root/'final-validation.json'
    if final.exists():raise ValueError('Do not overwrite sealed delivery')
    http=json.loads((root/'http-validation-62c65f1c-74e6-443a-833a-83dab1aac77c.json').read_text())
    browser=json.loads((root/'browser-validation.json').read_text())
    assert http['status']==browser['status']=='passed'
    logs=Path('.cache/stage24/acceptance');logs.mkdir(parents=True,exist_ok=True)
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromName('scripts.probe_personal_profile'),
                             unittest.defaultTestLoader.loadTestsFromName('scripts.probe_workbench_policy')])
    with (logs/'cpu-tests.log').open('w',encoding='utf-8') as stream,contextlib.redirect_stdout(stream),contextlib.redirect_stderr(stream):
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    if not result.wasSuccessful() or result.testsRun!=14:raise ValueError('CPU regression failed')
    old=verify_receipt(Path('reports/stage23/final-validation.json'),('code','browser_assets','docs','outputs','report','private_validation'))
    fields={15:('code','data','outputs','report'),16:('code','materials','outputs','private_data','report'),
        17:('code','docs','outputs','report','private_replay_assets'),18:('code','docs','outputs','report'),
        19:('code','outputs','private_data','docs','report'),20:('code','vendor','outputs','private_data','docs','report'),
        22:('code','docs','outputs','report','previous_receipts','private_data')}
    counts={str(k):verify_receipt(Path(f'reports/stage{k}/final-validation.json'),v) for k,v in fields.items()}
    counts['21-isolated']=verify_receipt(Path('reports/stage21-isolated/final-validation.json'),('code','outputs','private_data','invalidated_v1_assets','docs','report'))
    from scripts.manage_stage17_env import BASE,environment
    from gsearch.relocated_demo import verify_bundle
    bundle=verify_bundle(BASE/'replica')
    versions={d.metadata['Name']:d.version for d in metadata.distributions()}
    assert versions==json.loads(Path('reports/stage17/runtime-versions.json').read_text())['installed_versions']
    # Verify frozen browser libraries were not rewritten in the new version.
    for p in Path('web/papertrail/dist/vendor').iterdir():
        assert digest(p)==digest(Path('web/papertrail-v24/dist/vendor')/p.name)
    from gsearch.visitor_profile import Catalog
    catalog=Catalog()
    from scripts.personal_workbench_control import health
    code,value=health();assert code==200 and value['llm_enabled'] is False
    command=subprocess.run(['cmd.exe','/c',str(Path('personal-workbench.cmd').resolve()),'start','--no-open'],
        cwd=Path.home(),env=environment(),capture_output=True,text=True,check=True)
    assert json.loads(command.stdout)['state']=='already_running'
    code_files=['gsearch/visitor_profile.py','gsearch/personal_workbench.py','scripts/personal_workbench_control.py',
        'scripts/prepare_personal_workbench.py','scripts/adapt_personal_frontend.py','scripts/probe_personal_profile.py',
        'scripts/validate_personal_workbench.py','scripts/verify_personal_delivery.py','personal-workbench.cmd']
    docs=['docs/PERSONAL_WORKBENCH.md','web/papertrail-v24/THIRD_PARTY_NOTICES.md']
    reports=['reports/阶段24_个人兴趣画像与可计算解释.md']
    private=[*Path('data/stage24-personal/screenshots').glob('*.png'),logs/'cpu-tests.log']
    private+=[p for p in Path('data/stage24-personal/validation').rglob('*.json')]
    save(final,{'status':'complete_personal_profile_local','url':'http://127.0.0.1:8768','new_profile_tests':8,'existing_policy_tests':6,
        'total_cpu_tests':result.testsRun,'http_checks':http['count'],'browser_checks':len(browser['checks']),
        'text_representation_exact':catalog.signature,'stage23_assets_unchanged':old,'history_verified_assets':counts,
        'migrated_assets':len(bundle['files']),'unchanged_cpu_packages':len(versions),'absolute_launcher_from_home_passed':True,
        'human_confirmed_queries':http['quality_status']['query_confirmed'],'human_judged_pairs':http['quality_status']['human_judged_pairs'],
        'new_relevance_gain_claimed':False,'public_deployment':False,'physical_second_machine_tested':False,
        'code':{p:digest(Path(p)) for p in code_files},'browser_assets':{str(p):digest(p) for p in Path('web/papertrail-v24/dist').rglob('*') if p.is_file()},
        'docs':{p:digest(Path(p)) for p in docs},'report':{p:digest(Path(p)) for p in reports},
        'outputs':{str(p):digest(p) for p in root.glob('*.json') if p!=final},'private_validation':{str(p):digest(p) for p in private},
        'mutable_preferences_and_runtime_excluded':True,'later_work':'actual human judgments, further explanation usability, public permitted-data deployment'})
    print(json.dumps({'status':'complete','cpu_tests':result.testsRun,'http_checks':http['count'],'stage23_assets_unchanged':old,'receipt_sha256':digest(final)}))


if __name__=='__main__':main()
