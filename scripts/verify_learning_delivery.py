"""Seal the local beginner workflow while keeping deployment and human evaluation explicit."""
import importlib.metadata as metadata
import json
from pathlib import Path
import subprocess

from gsearch.quality_protocol import digest,save
from gsearch.showcase import verify_receipt
from scripts.verify_trial_delivery import GROUPS as PREVIOUS_GROUPS
from scripts.assemble_model_review import formal_state
from scripts.learning_control import health
from scripts.manage_stage17_env import environment

ROOT=Path('reports/stage40')
GROUPS=('code','bundle','docs','report','outputs','private_validation')


def load(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def main():
    final=ROOT/'final-validation.json'
    if final.exists():
        print({'verified_existing':True,'assets':verify_receipt(final,GROUPS),'sha256':digest(final)})
        return
    previous=verify_receipt(Path('reports/stage39/final-validation.json'),PREVIOUS_GROUPS)
    workspace=verify_receipt(Path('reports/stage38/final-validation.json'),('code','web','docs','report','outputs','private_validation'))
    core,browser,contrast=[load(ROOT/p) for p in ['core-validation.json','browser-validation.json','contrast-validation.json']]
    assert core['status']=='passed' and core['count']==50 and core['unchanged_response_count']==21
    assert browser['status']=='passed' and browser['test_preferences_cleaned'] and len(browser['checks'])==22
    assert load('.cache/stage40/failure-fixture/process.json')['state']=='stopped'
    assert contrast['status']=='passed' and contrast['sample_count']==11 and contrast['minimum_ratio']>=4.5
    assert not Path('deploy/stage40/render.yaml').exists()
    old_versions={d.metadata['Name']:d.version for d in metadata.distributions()}
    assert old_versions==load('reports/stage17/runtime-versions.json')['installed_versions']
    old_dep=load('reports/stage39/dependency-audit.json')
    result=subprocess.run([str(Path('.cache/stage39/runtime-secure/Scripts/python.exe').resolve()),'-E','-s','-c',
        "import importlib.metadata as m,json,sys;print(json.dumps({'python':sys.version,'packages':{d.metadata['Name']:d.version for d in m.distributions()}}))"],
        capture_output=True,text=True,check=True)
    current=json.loads(result.stdout)
    assert current['python'].startswith('3.12.16')
    assert current['packages']=={p['name']:p['version'] for p in old_dep['packages']}
    baseline=load('data/stage27-model-review/formal-baseline.json');formal=formal_state()
    assert formal=={k:baseline[k] for k in formal}
    for p in Path('deploy/stage39/catalog').rglob('*'):
        if p.is_file():assert digest(p)==digest(Path('deploy/stage40/catalog')/p.relative_to('deploy/stage39/catalog'))
    for name in ['catalog.py','security.py','reuse.py','__init__.py']:
        assert digest(Path('deploy/stage39/trialsite')/name)==digest(Path('deploy/stage40/trialsite')/name)
    old=Path('deploy/stage39/trialsite/app.py').read_text(encoding='utf-8')
    new=Path('deploy/stage40/trialsite/app.py').read_text(encoding='utf-8')
    assert new==old.replace('def main():','def main(factory=create_app):').replace('uvicorn.run(create_app(settings)','uvicorn.run(factory(settings)')
    changed={'main.mjs','topics.mjs','index.html'}
    for p in Path('deploy/stage39/web').rglob('*'):
        if p.is_file() and p.name not in changed:
            assert digest(p)==digest(Path('deploy/stage40/web')/p.relative_to('deploy/stage39/web'))
    assert digest(ROOT/'learning-paths.json')==digest(Path('deploy/stage40/learning-paths.json'))
    code=['scripts/prepare_learning_workspace.py','scripts/adapt_learning_workspace.py','scripts/run_learning_local.py',
          'scripts/prepare_learning_control.py','scripts/learning_control.py','scripts/validate_learning_workspace.py',
          'scripts/learning_failure_fixture.py','scripts/verify_learning_delivery.py','papertrail-learn.cmd']
    for p in [Path(p) for p in code]+list(Path('deploy/stage40/trialsite').glob('*.py')):
        if p.suffix=='.py':compile(p.read_text(encoding='utf-8'),str(p),'exec')
    node=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
    for p in Path('deploy/stage40/web').rglob('*.mjs'):
        subprocess.run([str(node),'--check',str(p)],capture_output=True,check=True)
    status,value=health();assert status==200 and value['release']=='stage40' and value['catalog']==162
    launch=subprocess.run(['cmd.exe','/c',str(Path('papertrail-learn.cmd').resolve()),'start','--no-open'],
        cwd=Path.home(),env=environment(),capture_output=True,text=True,check=True)
    assert json.loads(launch.stdout)['state']=='already_running'
    assert load('.cache/stage39/service.json')['state']=='stopped'
    for p in browser['screenshots']:assert Path(p).read_bytes().startswith(b'\xff\xd8\xff')
    save(ROOT/'validation.json',{'status':'passed_local_beginner_workflow','previous_stage39_assets_unchanged':previous,
        'previous_stage38_assets_unchanged':workspace,'old_packages_unchanged':len(old_versions),
        'isolated_packages_unchanged':len(current['packages']),'formal_state':formal,'core_checks':50,
        'unchanged_old_responses':21,'browser_checks':22,'contrast_samples':11,
        'minimum_sample_contrast':contrast['minimum_ratio'],'guide_papers':9,'catalog':162,
        'same_catalog_cookie_and_private_volume':True,'absolute_launcher_from_home':True,
        'reading_module_and_algorithms_unchanged':True,'test_preferences_cleaned':True,
        'failure_fixture_stopped':True,'service_instance':value['instance_id'],
        'public_deployed':False,'free_database_adapted':False,'human_learning_effect_evaluated':False})
    bundle=[p for p in Path('deploy/stage40').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    assert not any(p.suffix in ['.key','.sqlite3','.pyc'] for p in bundle)
    save(final,{'status':'complete_local_beginner_workflow','url':'http://127.0.0.1:8785/',
        'code':{p:digest(Path(p)) for p in code},'bundle':{str(p):digest(p) for p in bundle},
        'docs':{p:digest(Path(p)) for p in ['docs/PRODUCT_POSITIONING_V40.md','docs/PAPERTRAIL_LEARNING_V40.md']},
        'report':{'reports/阶段40_初学者定位与阅读路径.md':digest(Path('reports/阶段40_初学者定位与阅读路径.md'))},
        'outputs':{str(p):digest(p) for p in ROOT.glob('*.json') if p!=final},
        'private_validation':{p:digest(Path(p)) for p in browser['screenshots']+['data/stage40-ui/contrast-colors.json']},
        'mutable_preferences_keys_and_test_stores_excluded':True,
        'not_claimed':['public free hosting','human relevance/learning gain','complete Agent curriculum']})
    print({'sealed':True,'assets':verify_receipt(final,GROUPS),'sha256':digest(final)})


if __name__=='__main__':main()
