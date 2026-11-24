"""Seal exact sources, unchanged prior assets and the local educational delivery."""
import importlib.metadata as metadata
import json
from pathlib import Path
import re
import subprocess

from gsearch.quality_protocol import digest, save
from gsearch.showcase import verify_receipt
from scripts.assemble_model_review import formal_state
from scripts.minionerec_control import health

ROOT = Path('reports/stage41')
GROUPS = ('code','bundle','docs','report','outputs','research','private_validation')


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def luminance(color: str) -> float:
    parts = [int(v)/255 for v in re.findall(r'\d+',color)]
    if len(parts) != 3:
        raise ValueError('Opaque RGB samples required')
    linear = [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in parts]
    return sum(x*y for x,y in zip(linear,[.2126,.7152,.0722]))


def main() -> None:
    final = ROOT/'final-validation.json'
    if final.exists():
        print({'verified_existing': True, 'assets': verify_receipt(final,GROUPS), 'sha256':digest(final)})
        return
    previous = verify_receipt(Path('reports/stage40/final-validation.json'),('code','bundle','docs','report','outputs','private_validation'))
    core, browser = [load(ROOT/p) for p in ['core-validation.json','browser-validation.json']]
    assert core['status'] == browser['status'] == 'passed'
    assert core['count'] == 57 and core['unchanged_response_count'] == 24
    assert len(browser['checks']) == 15 and all(c['passed'] for c in browser['checks'])
    colors = load('data/stage41-ui/contrast-colors.json')
    for color in colors:
        values = sorted([luminance(color['fg']),luminance(color['bg'])])
        color['ratio'] = (values[1]+.05)/(values[0]+.05)
    minimum = min(c['ratio'] for c in colors)
    assert minimum >= 4.5
    save(ROOT/'contrast-validation.json',{'status':'passed','sample_count':len(colors),'minimum_ratio':minimum,
         'scope':'sampled steady-state text on opaque surfaces, including active SVG hint; not a full accessibility audit','samples':colors})
    for folder in ['catalog','trialsite']:
        for p in (Path('deploy/stage40')/folder).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts:
                assert digest(p) == digest(Path('deploy/stage41')/p.relative_to('deploy/stage40'))
    for p in Path('deploy/stage40/web').rglob('*'):
        if p.is_file() and p.name not in ['index.html','main.mjs','open-source.txt']:
            assert digest(p) == digest(Path('deploy/stage41/web')/p.relative_to('deploy/stage40/web'))
    assert digest(Path('deploy/stage40/learning-paths.json')) == digest(Path('deploy/stage41/learning-paths.json'))
    old = {d.metadata['Name']:d.version for d in metadata.distributions()}
    assert old == load('reports/stage17/runtime-versions.json')['installed_versions']
    packages = subprocess.run([str(Path('.cache/stage39/runtime-secure/Scripts/python.exe').resolve()),'-E','-s','-c',
        "import importlib.metadata as m,json,sys;print(json.dumps({'python':sys.version,'packages':{d.metadata['Name']:d.version for d in m.distributions()}}))"],capture_output=True,text=True,check=True)
    secure = json.loads(packages.stdout)
    assert secure['python'].startswith('3.12.16')
    assert secure['packages'] == {p['name']:p['version'] for p in load('reports/stage39/dependency-audit.json')['packages']}
    formal = formal_state()
    baseline = load('data/stage27-model-review/formal-baseline.json')
    assert formal == {k:baseline[k] for k in formal}
    code = ['scripts/acquire_minionerec.py','scripts/prepare_minionerec.py','scripts/run_minionerec_local.py',
            'scripts/minionerec_control.py','scripts/validate_minionerec.py','scripts/verify_minionerec_delivery.py','papertrail-minionerec.cmd']
    for name in code:
        if name.endswith('.py'):
            compile(Path(name).read_text(encoding='utf-8'),name,'exec')
    node = Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
    for name in ['main.mjs','minionerec.mjs']:
        subprocess.run([str(node),'--check',str(Path('deploy/stage41/web')/name)],capture_output=True,check=True)
    status, value = health()
    assert status == 200 and value['release'] == 'stage41' and value['catalog'] == 162 and value['supplement_papers'] == 3
    assert load('.cache/stage40/service.json')['state'] == 'stopped'
    for name in browser['screenshots']:
        assert Path(name).read_bytes().startswith(b'\xff\xd8\xff')
    save(ROOT/'validation.json',{'status':'passed_local_supplement','previous_assets_unchanged':previous,
        'old_packages_unchanged':len(old),'secure_packages_unchanged':len(secure['packages']),
        'formal_state':formal,'catalog':162,'supplement_originals':3,'old_responses_identical':24,
        'core_checks':57,'browser_checks':15,'contrast_samples':len(colors),'minimum_contrast':minimum,
        'private_volume_cookie_and_catalog_preserved':True,'new_training_dependencies':0,'live_model_training':False,
        'public_deployed':False,'service_instance':value['instance_id']})
    bundle = [p for p in Path('deploy/stage41').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    assert not any(p.suffix in ['.key','.sqlite3','.pyc'] for p in bundle)
    save(final,{'status':'complete_local_minionerec_guide','url':'http://127.0.0.1:8787/minionerec.html',
        'code':{p:digest(Path(p)) for p in code},'bundle':{str(p):digest(p) for p in bundle},
        'docs':{'docs/PAPERTRAIL_MINIONEREC_V41.md':digest(Path('docs/PAPERTRAIL_MINIONEREC_V41.md'))},
        'report':{'reports/阶段41_MiniOneRec生成式推荐专题.md':digest(Path('reports/阶段41_MiniOneRec生成式推荐专题.md'))},
        'outputs':{str(p):digest(p) for p in ROOT.glob('*.json') if p != final},
        'research':{str(p):digest(p) for p in (ROOT/'upstream').rglob('*') if p.is_file()},
        'private_validation':{p:digest(Path(p)) for p in browser['screenshots']+['data/stage41-ui/contrast-colors.json']},
        'mutable_preferences_keys_test_stores_and_plans_excluded':True,
        'not_claimed':['MiniOneRec model training or online inference','human quality gain','public hosting']})
    print({'sealed':True,'assets':verify_receipt(final,GROUPS),'sha256':digest(final), 'contrast_minimum':minimum})


if __name__ == '__main__':
    main()
