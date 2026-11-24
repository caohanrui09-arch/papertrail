"""Verify independent v2 artifacts, historical integrity and model-only provenance."""
import importlib.metadata as metadata
from pathlib import Path
import json

from gsearch.quality_protocol import digest,save
from gsearch.showcase import verify_receipt
from scripts.assemble_model_review import formal_state
from scripts.build_search_v2 import ROOT,ANCHORS,AT,load

REPORT=Path('reports/stage29')
GROUPS=('code','docs','report','outputs','private_data','raw')


def main() -> None:
 receipt=REPORT/'final-validation.json'
 if receipt.exists():
  print(json.dumps({'verified_existing':True,'assets':verify_receipt(receipt,GROUPS),'receipt_sha256':digest(receipt)}));return
 docs=load(ROOT/'documents.json');catalog=load(ROOT/'catalog-receipt.json')
 assert len(docs)==42 and digest(ROOT/'documents.json')==catalog['documents_sha256']
 assert not catalog['missing'] and not catalog['rejected'] and set(catalog['anchors_present'])==set(ANCHORS)
 raw={}
 for r in docs:
  p=Path(r['provenance']['raw_path']);assert digest(p)==r['provenance']['raw_sha256']
  raw[str(p)]=digest(p);assert r['version']==1 and r['source_verified'] is True
  assert r['available_at']<=AT and r['title'].strip() and r['abstract'].strip()
 for suffix in ('','-reviewed'):
  scenes=load(ROOT/('synthetic-scenarios'+suffix+'.json'));result=load(ROOT/('paired-diagnostic'+suffix+'.json'))
  assert scenes['real_user_feedback'] is False and result['human_labels']==0
  assert result['quality_metrics_computed'] is False and result['weights_tuned'] is False
  assert result['source_versions_verified']==42 and len(result['scenarios'])==3
  for s in result['scenarios']:
   base={p['doc_id'] for p in s['core_bm25']}
   assert not base&set(scenes['shared_seen_filter'])
   for condition,rank in s['fixed_candidate_reranking'].items():
    assert {p['doc_id'] for p in rank}==base and len(rank)==len(base)
 old={}
 for n,groups in {20:('code','vendor','outputs','private_data','docs','report'),23:('code','browser_assets','docs','outputs','report','private_validation'),24:('code','browser_assets','docs','report','outputs','private_validation'),26:('code','browser_assets','docs','report','outputs','private_pool','private_validation'),27:('code','docs','report','outputs','private_review'),28:('code','report','outputs','private_diagnostic')}.items():
  old[str(n)]=verify_receipt(Path(f'reports/stage{n}/final-validation.json'),groups)
 prior=load(Path('reports/stage25/validation.json'))['assets']
 assert all(digest(Path(p))==v for p,v in prior.items())
 assert digest(Path('data/stage13-expansion/documents.json'))==load(ROOT/'plan.json')['old_corpus_sha256']
 versions={d.metadata['Name']:d.version for d in metadata.distributions()}
 assert versions==load(Path('reports/stage17/runtime-versions.json'))['installed_versions']
 baseline=load(Path('data/stage27-model-review/formal-baseline.json'));state=formal_state()
 assert state=={k:baseline[k] for k in state}
 code=['scripts/build_search_v2.py','scripts/evaluate_search_v2.py','scripts/verify_search_v2.py']
 for p in code:compile(Path(p).read_text(encoding='utf-8'),p,'exec')
 save(REPORT/'validation.json',{'documents':42,'source_versions_verified':42,'anchor_checks':6,
  'initial_and_reviewed_variants':2,'paired_conditions_per_variant':6,'candidate_sets_preserved':True,
  'old_assets_unchanged':old,'stage25_assets_unchanged':len(prior),'cpu_packages_unchanged':len(versions),
  'formal_state':state,'human_metrics':False,'website_integration':False,'public_deployment':False})
 report=Path('reports/阶段29_独立主题搜索v2首批验证.md')
 save(receipt,{'status':'complete_bounded_v2_development_chain','code':{p:digest(Path(p)) for p in code},
  'docs':{'THIRD_PARTY_NOTICES.md':digest(Path('THIRD_PARTY_NOTICES.md'))},'report':{str(report):digest(report)},
  'outputs':{str(p):digest(p) for p in REPORT.glob('*.json') if p!=receipt},
  'private_data':{str(p):digest(p) for p in ROOT.rglob('*') if p.is_file()},'raw':raw})
 print(json.dumps({'status':'sealed','documents':42,'assets':verify_receipt(receipt,GROUPS),'receipt_sha256':digest(receipt)}))


if __name__=='__main__':main()
