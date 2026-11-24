"""Seal the CPU experiment, exact reuse and the read-only interactive delivery."""
import importlib.metadata as metadata
import json
from pathlib import Path
import subprocess

from gsearch.quality_protocol import digest, save
from gsearch.showcase import verify_receipt
from scripts.assemble_model_review import formal_state
from scripts.sid_control import health
from scripts.verify_minionerec_delivery import luminance

ROOT = Path('reports/stage43')
GROUPS = ('code','bundle','docs','report','outputs','experiment','upstream','private_validation')


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main() -> None:
    final = ROOT/'final-validation.json'
    if final.exists():
        print({'verified_existing':True,'assets':verify_receipt(final,GROUPS),'sha256':digest(final)})
        return
    prior = verify_receipt(Path('reports/stage41/final-validation.json'),('code','bundle','docs','report','outputs','research','private_validation'))
    core, diagnostic, browser = [load(ROOT/name) for name in ['core-validation.json','diagnostic-validation.json','browser-validation.json']]
    assert core['status']==diagnostic['status']==browser['status']=='passed'
    assert core['count']==68 and core['unchanged_response_count']==25
    assert diagnostic['count']==563 and diagnostic['upstream_tests']==4
    assert len(browser['checks'])==21 and all(c['passed'] for c in browser['checks'])
    colors = load('data/stage43-ui/contrast-colors.json')
    for c in colors:
        a,b = sorted([luminance(c['fg']),luminance(c['bg'])])
        c['ratio']=(b+.05)/(a+.05)
    minimum = min(c['ratio'] for c in colors)
    assert minimum>=4.5
    save(ROOT/'contrast-validation.json',{'status':'passed','sample_count':len(colors),'minimum_ratio':minimum,
         'scope':'steady-state sampled text on opaque surfaces; disabled controls, all interaction states and full accessibility not certified','samples':colors})
    for p in Path('deploy/stage41/catalog').rglob('*'):
        if p.is_file():
            assert digest(p)==digest(Path('deploy/stage43')/p.relative_to('deploy/stage41'))
    for p in Path('deploy/stage41/trialsite').glob('*.py'):
        assert digest(p)==digest(Path('deploy/stage43/trialsite')/p.name)
    changed = {'main.mjs','minionerec.mjs','minionerec.css','open-source.txt'}
    for p in Path('deploy/stage41/web').rglob('*'):
        if p.is_file() and p.name not in changed:
            assert digest(p)==digest(Path('deploy/stage43/web')/p.relative_to('deploy/stage41/web'))
    for name in ['project.json','project-original.atom','learning-paths.json','requirements.lock']:
        assert digest(Path('deploy/stage41')/name)==digest(Path('deploy/stage43')/name)
    versions={d.metadata['Name']:d.version for d in metadata.distributions()}
    assert versions==load('reports/stage17/runtime-versions.json')['installed_versions']
    secure = json.loads(subprocess.run([str(Path('.cache/stage39/runtime-secure/Scripts/python.exe').resolve()),'-E','-s','-c',
        "import importlib.metadata as m,json,sys;print(json.dumps({'python':sys.version,'packages':{d.metadata['Name']:d.version for d in m.distributions()}}))"],
        capture_output=True,text=True,check=True).stdout)
    assert secure['python'].startswith('3.12.16')
    assert secure['packages']=={p['name']:p['version'] for p in load('reports/stage39/dependency-audit.json')['packages']}
    formal=formal_state()
    baseline=load('data/stage27-model-review/formal-baseline.json')
    assert formal=={k:baseline[k] for k in formal}
    test_source=load(ROOT/'test-source.json')
    import hashlib
    b=Path(test_source['vendored']).read_bytes()
    assert hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()==test_source['blob']
    result=load(ROOT/'results.json')
    assert not result['decision']['sft_started'] and not result['decision']['rl_started']
    assert result['training_supervision']['within_catalog_next_item_pairs']==33
    assert load('deploy/stage43/sid-lab-receipt.json')['results_sha256']==digest(ROOT/'results.json')
    code=['scripts/prepare_sid_protocol.py','scripts/run_sid_diagnostics.py','scripts/prepare_sid_workspace.py',
          'scripts/validate_sid_diagnostics.py','scripts/validate_sid_workspace.py','scripts/run_sid_local.py',
          'scripts/sid_control.py','scripts/verify_sid_delivery.py','papertrail-sid.cmd']
    for name in code:
        if name.endswith('.py'):
            compile(Path(name).read_text(encoding='utf-8'),name,'exec')
    node=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
    for name in ['main.mjs','minionerec.mjs','sid-lab.mjs']:
        subprocess.run([str(node),'--check',str(Path('deploy/stage43/web')/name)],capture_output=True,check=True)
    status,value=health()
    assert status==200 and value['release']=='stage43' and value['catalog']==162 and value['sid_models']==3
    assert load('.cache/stage41/service.json')['state']=='stopped'
    for name in browser['screenshots']:
        assert Path(name).read_bytes().startswith(b'\xff\xd8\xff')
    save(ROOT/'validation.json',{'status':'passed_cpu_structure_and_local_ui','previous_stage41_assets_unchanged':prior,
        'old_packages_unchanged':len(versions),'secure_packages_unchanged':len(secure['packages']),
        'formal_state':formal,'core_checks':68,'old_responses_identical':25,'diagnostic_assertions':563,
        'upstream_regression_tests':4,'browser_checks':21,'contrast_samples':len(colors),'minimum_contrast':minimum,
        'catalog':162,'fit_models':3,'controlled_permutations':60,'private_volume_preserved':True,
        'test_preferences_changed':False,'sft_started':False,'rl_started':False,'public_deployed':False,
        'service_instance':value['instance_id']})
    bundle=[p for p in Path('deploy/stage43').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    assert not any(p.suffix in ['.key','.sqlite3','.pyc'] for p in bundle)
    save(final,{'status':'complete_cpu_structure_diagnostics','url':'http://127.0.0.1:8789/sid-lab.html',
        'code':{p:digest(Path(p)) for p in code},'bundle':{str(p):digest(p) for p in bundle},
        'docs':{'docs/PAPERTRAIL_SID_LAB_V43.md':digest(Path('docs/PAPERTRAIL_SID_LAB_V43.md'))},
        'report':{'reports/阶段43_官方CPU_SID诊断与受控对照.md':digest(Path('reports/阶段43_官方CPU_SID诊断与受控对照.md'))},
        'outputs':{str(p):digest(p) for p in ROOT.glob('*.json') if p!=final},
        'experiment':{str(p):digest(p) for p in Path('data/stage43-sid').rglob('*') if p.is_file()},
        'upstream':{str(p):digest(p) for p in Path('third_party/minionerec_sid_cpu').rglob('*') if p.is_file() and '__pycache__' not in p.parts},
        'private_validation':{p:digest(Path(p)) for p in browser['screenshots']+['data/stage43-ui/contrast-colors.json']},
        'mutable_preferences_keys_test_stores_and_plans_excluded':True,
        'not_claimed':['neural embedding or MiniOneRec paper reproduction','recommendation quality improvement','SFT/RL training','public hosting']})
    print({'sealed':True,'assets':verify_receipt(final,GROUPS),'sha256':digest(final),'minimum_contrast':minimum})


if __name__=='__main__':
    main()
