"""Seal reviewed-topic web delivery; mutable process state excluded."""
import importlib.metadata as metadata
import json
from pathlib import Path
import subprocess
from gsearch.quality_protocol import digest,save
from gsearch.showcase import verify_receipt
from scripts.assemble_model_review import formal_state
from scripts.search_v2_control import health
from scripts.manage_stage17_env import environment

ROOT=Path('reports/stage30')
GROUPS=('code','web','docs','report','outputs','private_review')


def load(p):return json.loads(Path(p).read_text(encoding='utf-8'))


def main():
 receipt=ROOT/'final-validation.json'
 if receipt.exists():
  print(json.dumps({'verified_existing':True,'assets':verify_receipt(receipt,GROUPS),'sha256':digest(receipt)}));return
 rows=load('data/stage29-search-v2/documents.json');docs={r['doc_id']:r for r in rows}
 review=load('data/stage30-search-review/review.json');assert len(review['judgments'])==126
 assert review['catalog_sha256']==digest(Path('data/stage29-search-v2/documents.json'))
 assert len({(r['topic'],r['doc_id']) for r in review['judgments']})==126
 for row in review['judgments']:
  assert row['evidence'] in docs[row['doc_id']]['abstract'] and row['human'] is False and row['independent'] is False
  assert row['version_key']==docs[row['doc_id']]['version_key']
 http=load(ROOT/'http-validation.json');assert http['status']=='passed' and http['count']==37
 browser=load(ROOT/'browser-validation.json');assert len(browser['checks'])==12 and browser['status']=='passed_desktop_interactions'
 screenshot=Path(browser['screenshot']);assert screenshot.suffix=='.jpg' and screenshot.read_bytes().startswith(b'\xff\xd8\xff')
 for p in Path('web/papertrail-v30/dist/vendor').iterdir():assert digest(p)==digest(Path('web/papertrail-v26/dist/vendor')/p.name)
 old={}
 for stage,groups in {20:('code','vendor','outputs','private_data','docs','report'),23:('code','browser_assets','docs','outputs','report','private_validation'),24:('code','browser_assets','docs','report','outputs','private_validation'),26:('code','browser_assets','docs','report','outputs','private_pool','private_validation'),27:('code','docs','report','outputs','private_review'),28:('code','report','outputs','private_diagnostic'),29:('code','docs','report','outputs','private_data','raw')}.items():
  old[str(stage)]=verify_receipt(Path(f'reports/stage{stage}/final-validation.json'),groups)
 previous=load('reports/stage25/validation.json')['assets'];assert all(digest(Path(p))==v for p,v in previous.items())
 versions={d.metadata['Name']:d.version for d in metadata.distributions()}
 assert versions==load('reports/stage17/runtime-versions.json')['installed_versions']
 state=formal_state();baseline=load('data/stage27-model-review/formal-baseline.json');assert state=={k:baseline[k] for k in state}
 code=['gsearch/search_v2_workbench.py','scripts/package_search_review.py','scripts/search_v2_control.py','scripts/validate_search_v2_http.py','scripts/verify_search_v2_web.py','search-v2.cmd']
 for name in code:
  if name.endswith('.py'):compile(Path(name).read_text(encoding='utf-8'),name,'exec')
 node=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
 subprocess.run([str(node),'--check','web/papertrail-v30/dist/app.mjs'],check=True,capture_output=True)
 status,health_value=health();assert status==200 and health_value['llm_enabled'] is False
 launched=subprocess.run(['cmd.exe','/c',str(Path('search-v2.cmd').resolve()),'start','--no-open'],cwd=Path.home(),env=environment(),text=True,capture_output=True,check=True)
 assert json.loads(launched.stdout)['state']=='already_running'
 save(ROOT/'validation.json',{'status':'passed','judgments':126,'http_checks':37,'browser_checks':12,
  'old_assets_unchanged':old,'stage25_assets_unchanged':len(previous),'unchanged_cpu_packages':len(versions),
  'formal_state':state,'absolute_launcher_from_home':True,'service_instance_at_delivery':health_value['instance_id'],
  'mobile_visual_acceptance_deferred':True,'public_deployment':False})
 report=Path('reports/阶段30_v2相关性审查与网站入口.md')
 save(receipt,{'status':'complete_reviewed_search_v2_local_web','url':'http://127.0.0.1:8770',
  'code':{p:digest(Path(p)) for p in code},'web':{str(p):digest(p) for p in Path('web/papertrail-v30/dist').rglob('*') if p.is_file()},
  'docs':{'web/papertrail-v30/THIRD_PARTY_NOTICES.md':digest(Path('web/papertrail-v30/THIRD_PARTY_NOTICES.md'))},
  'report':{str(report):digest(report)},'outputs':{str(p):digest(p) for p in ROOT.glob('*.json') if p!=receipt},
  'private_review':{str(p):digest(p) for p in Path('data/stage30-search-review').iterdir() if p.is_file()},
  'mutable_runtime_excluded':True})
 print(json.dumps({'status':'sealed','url':'http://127.0.0.1:8770','assets':verify_receipt(receipt,GROUPS),'sha256':digest(receipt)}))


if __name__=='__main__':main()
