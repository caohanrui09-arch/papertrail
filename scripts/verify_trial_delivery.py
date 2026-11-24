"""Seal only the trial preparation; explicitly retain outstanding public deployment."""
import ast
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import re
import subprocess

from gsearch.quality_protocol import digest, save
from gsearch.showcase import verify_receipt
from scripts.assemble_model_review import formal_state
from scripts.trial_control import health
from scripts.manage_stage17_env import environment

ROOT=Path('reports/stage39')
GROUPS=('code','bundle','docs','report','outputs','private_validation','acquisition','raw','archive')


def load(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def main():
    final=ROOT/'final-validation.json'
    if final.exists():
        print({'verified_existing':True,'assets':verify_receipt(final,GROUPS),'sha256':digest(final)})
        return
    stages={20:('code','vendor','outputs','private_data','docs','report'),
        23:('code','browser_assets','docs','outputs','report','private_validation'),
        24:('code','browser_assets','docs','report','outputs','private_validation'),
        26:('code','browser_assets','docs','report','outputs','private_pool','private_validation'),
        27:('code','docs','report','outputs','private_review'),28:('code','report','outputs','private_diagnostic'),
        29:('code','docs','report','outputs','private_data','raw'),30:('code','web','docs','report','outputs','private_review')}
    oldgroups=('code','web','docs','report','outputs','private_validation')
    stages.update({s:oldgroups for s in [32,33,34,35,36,38]});stages[37]=oldgroups+('reference',)
    old={str(s):verify_receipt(Path(f'reports/stage{s}/final-validation.json'),g) for s,g in stages.items()}
    for s,key in [(25,'assets'),(31,'files')]:
        files=load(f'reports/stage{s}/validation.json')[key]
        if not all(digest(Path(p))==v for p,v in files.items()):raise ValueError('Old assets changed')
        old[str(s)]=len(files)
    versions={d.metadata['Name']:d.version for d in metadata.distributions()}
    assert versions==load('reports/stage17/runtime-versions.json')['installed_versions']
    baseline=load('data/stage27-model-review/formal-baseline.json')
    state=formal_state();assert state=={k:baseline[k] for k in state}
    assert digest(Path('.cache/stage17/bootstrap/uv.exe'))==load('reports/stage17/bootstrap-source.json')['executable_sha256']
    package=load(ROOT/'package.json');replica=load(ROOT/'replica-validation.json')
    assert package['count']==48 and not package['private_data_included'] and not package['published']
    assert replica['status']=='passed' and replica['archive_sha256']==package['zip_sha256'] and replica['fixture_stopped']
    assert digest(Path(package['zip']))==package['zip_sha256']
    assert all(digest(Path('deploy/stage39')/name)==v for name,v in package['files'].items())
    audit=load(ROOT/'dependency-audit.json')
    assert len(audit['packages'])==26 and audit['advisories']==[] and not audit.get('osv_error')
    assert audit['python'].startswith('3.12.16')
    assert load(ROOT/'security-validation.json')['passed']==72
    assert load(ROOT/'http-validation.json')['passed']==42 and load(ROOT/'http-validation.json')['fixture_stopped']
    assert load(ROOT/'blueprint-validation.json')['status']=='passed'
    browser=load(ROOT/'browser-validation.json')
    assert browser['status']=='passed' and browser['test_preferences_cleaned'] and len(browser['checks'])==19
    for name in browser['screenshots']:assert Path(name).read_bytes().startswith(b'\xff\xd8\xff')
    # Check generated primitive ASTs against the exact selected old source definitions.
    reused=load('deploy/stage39/reuse-receipt.json')
    generated=ast.parse(Path('deploy/stage39/trialsite/reuse.py').read_text(encoding='utf-8'))
    for item in reused['primitives']:
        assert digest(Path(item['source']))==item['source_sha256']
        node=next(n for n in ast.parse(Path(item['source']).read_text(encoding='utf-8')).body if getattr(n,'name',None)==item['name'])
        if item['methods']!='all':node.body=[n for n in node.body if isinstance(n,ast.FunctionDef) and n.name in item['methods']]
        actual=next(n for n in generated.body if getattr(n,'name',None)==item['name'])
        assert ast.dump(actual,include_attributes=False)==ast.dump(node,include_attributes=False)
        assert hashlib.sha256(ast.dump(actual,include_attributes=False).encode()).hexdigest()==item['ast_sha256']
    assert digest(Path('deploy/stage39/trialsite/reuse.py'))==reused['generated_sha256']
    for path in Path('web/papertrail-v38/dist').rglob('*'):
        if path.is_file() and path.name not in ['main.mjs','backup.mjs']:
            assert digest(path)==digest(Path('deploy/stage39/web')/path.relative_to('web/papertrail-v38/dist'))
    node=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
    for path in Path('deploy/stage39/web').rglob('*.mjs'):
        subprocess.run([str(node),'--check',str(path)],capture_output=True,check=True)
    code=['scripts/build_trial_catalog.py','scripts/prepare_trial_bundle.py','scripts/prepare_trial_control.py',
          'scripts/trial_control.py','scripts/run_trial_local.py','scripts/validate_trial.py','scripts/validate_trial_http.py',
          'scripts/audit_trial_dependencies.py','scripts/validate_trial_blueprint.py','scripts/package_trial.py',
          'scripts/validate_trial_replica.py','scripts/verify_trial_delivery.py','papertrail-trial.cmd']
    for name in code:
        if name.endswith('.py'):compile(Path(name).read_text(encoding='utf-8'),name,'exec')
    status,value=health();assert status==200 and value['catalog']==162 and not value['llm_enabled']
    launch=subprocess.run(['cmd.exe','/c',str(Path('papertrail-trial.cmd').resolve()),'start','--no-open'],
                cwd=Path.home(),env=environment(),capture_output=True,text=True,check=True)
    assert json.loads(launch.stdout)['state']=='already_running'
    # No test feedback remains in the real preview store. Do not output identities.
    import sqlite3
    store=next(Path('data/stage39-visitors').glob('*.sqlite3'))
    with sqlite3.connect(store) as db:assert db.execute('SELECT count(*) FROM preferences').fetchone()[0]==0
    save(ROOT/'validation.json',{'status':'passed_local_preparation','catalog':162,'new_papers':120,
         'asgi_checks':72,'real_http_checks':42,'ui_checks':19,'standalone_checks':len(replica['checks']),
         'unchanged_old_assets':old,'unchanged_old_packages':len(versions),'formal_state':state,
         'reused_ast_primitives':len(reused['primitives']),'archive_files':48,'absolute_launcher_from_home':True,
         'test_preferences_cleaned':True,'temporary_services_stopped':True,'service_instance':value['instance_id'],
         'public_deployment':False,'live_tls_verified':False,'linux_or_second_machine_verified':False,
         'pending':'Owner choice of hosting account and recurring budget, then public TLS/persistence/network acceptance'})
    acquisition=[p for p in Path('data/stage39-trial').rglob('*.json')]
    raws={Path(r['provenance']['raw_path']) for r in load('data/stage39-trial/candidates.json')['records']}
    save(final,{'status':'complete_local_trial_preparation_not_deployed','url':'http://127.0.0.1:8782/',
         'code':{p:digest(Path(p)) for p in code},
         'bundle':{str(Path('deploy/stage39')/name):v for name,v in package['files'].items()},
         'docs':{'docs/PAPERTRAIL_TRIAL_V39.md':digest(Path('docs/PAPERTRAIL_TRIAL_V39.md'))},
         'report':{'reports/阶段39_小范围试用与目录扩容.md':digest(Path('reports/阶段39_小范围试用与目录扩容.md'))},
         'outputs':{str(p):digest(p) for p in ROOT.glob('*.json') if p!=final},
         'private_validation':{p:digest(Path(p)) for p in browser['screenshots']},
         'acquisition':{str(p):digest(p) for p in acquisition},'raw':{str(p):digest(p) for p in raws},
         'archive':{package['zip']:package['zip_sha256']},'visitor_database_and_keys_excluded':True,
         'not_claimed':['public URL','live TLS','Linux or container','second-machine reproduction','human relevance improvement']})
    print({'sealed_preparation':True,'assets':verify_receipt(final,GROUPS),'sha256':digest(final)})


if __name__=='__main__':main()
