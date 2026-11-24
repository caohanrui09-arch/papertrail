"""Seal the local licensed dataset and frozen evaluation without claiming training."""
import importlib.metadata as metadata
import json
from pathlib import Path
import subprocess
import sys

from gsearch.quality_protocol import digest,save
from gsearch.showcase import verify_receipt
from scripts.assemble_model_review import formal_state

ROOT=Path('reports/stage44')
DATA=Path('data/stage44-supervision')
GROUPS=('code','docs','report','outputs','local_data')


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main() -> None:
    final=ROOT/'final-validation.json'
    if final.exists():
        print({'verified_existing':True,'assets':verify_receipt(final,GROUPS),'sha256':digest(final)})
        return
    previous=verify_receipt(Path('reports/stage43/final-validation.json'),('code','bundle','docs','report','outputs','experiment','upstream','private_validation'))
    checked=load(ROOT/'validation.json')
    assert checked['status']=='passed' and checked['train_samples_reconstructed']==98887 and checked['synthetic_tests']==20
    assert checked['profiles_reconstructed']==11165 and checked['candidate_feedback_reconstructed']==152486
    assert checked['heldout_reconstructed']['tuning']['positive_events']==46352
    assert checked['heldout_reconstructed']['dev_descriptive']['positive_events']==49533
    receipt=load(DATA/'build-receipt.json')
    for name,expected in receipt['files'].items():assert digest(Path(name))==expected
    evaluation=load(ROOT/'evaluation-lock.json')
    for name,expected in evaluation['files'].items():assert digest(Path(name))==expected
    readiness=load(ROOT/'readiness.json')
    assert readiness['supervision_prepared'] and readiness['evaluation_contract_frozen']
    assert not any(readiness[k] for k in ['training_run_frozen','sft_started','rl_started','fresh_independent_test'])
    versions={d.metadata['Name']:d.version for d in metadata.distributions()}
    assert versions==load('reports/stage17/runtime-versions.json')['installed_versions']
    secure=json.loads(subprocess.run([str(Path('.cache/stage39/runtime-secure/Scripts/python.exe').resolve()),'-E','-s','-c',
        "import importlib.metadata as m,json,sys;print(json.dumps({'python':sys.version,'packages':{d.metadata['Name']:d.version for d in m.distributions()}}))"],capture_output=True,text=True,check=True).stdout)
    assert secure['packages']=={p['name']:p['version'] for p in load('reports/stage39/dependency-audit.json')['packages']}
    assert secure['python'].startswith('3.12.16')
    formal=formal_state();baseline=load('data/stage27-model-review/formal-baseline.json')
    assert formal=={k:baseline[k] for k in formal}
    ignored=subprocess.run(['git','check-ignore','--quiet',str(DATA/'train.next_item.jsonl')],capture_output=True)
    assert ignored.returncode==0
    target=Path('.cache/stage44/template-check-result.json')
    target.parent.mkdir(parents=True,exist_ok=True)
    assert not target.exists()
    rejected=subprocess.run([sys.executable,'-E','-s','-m','scripts.score_supervision','--split','tuning',
        '--run-lock',str(ROOT/'run-lock.template.json'),'--predictions',str(target.parent/'nonexistent-predictions.jsonl'),
        '--output',str(target)],capture_output=True,text=True)
    assert rejected.returncode!=0 and 'Exact training run not frozen' in rejected.stderr and not target.exists()
    (ROOT/'run-gate-rejection.log').write_text(rejected.stdout+rejected.stderr,encoding='utf-8')
    code=['gsearch/supervision.py','gsearch/supervision_evaluation.py','scripts/prepare_supervision_protocol.py',
          'scripts/build_supervision.py','scripts/freeze_supervision_evaluation.py','scripts/score_supervision.py',
          'scripts/validate_supervision.py','scripts/verify_supervision_delivery.py','tests/test_supervision.py']
    for name in code:compile(Path(name).read_text(encoding='utf-8'),name,'exec')
    save(ROOT/'release-validation.json',{'status':'passed_local_supervision_and_frozen_evaluation','previous_stage43_assets_unchanged':previous,
        'old_packages_unchanged':len(versions),'secure_packages_unchanged':len(secure['packages']),'formal_state':formal,
        'catalog':9000,'train_samples':98887,'profiles':11165,'candidate_feedback':152486,
        'heldout_positive_events':95885,'synthetic_tests':20,'source_reconstruction_checks':checked['check_count'],
        'empty_training_run_template_rejected':True,'derived_interactions_git_ignored':True,
        'model_training_started':False,'website_changed':False,'independent_fresh_test_available':False,
        'data_scope':'local noncommercial derived interactions; no redistribution'})
    save(final,{'status':'complete_local_supervision_and_evaluation_contract',
        'code':{p:digest(Path(p)) for p in code},
        'docs':{'docs/SFT_DATA_EVALUATION_V44.md':digest(Path('docs/SFT_DATA_EVALUATION_V44.md'))},
        'report':{'reports/阶段44_真实监督补齐与评价冻结.md':digest(Path('reports/阶段44_真实监督补齐与评价冻结.md'))},
        'outputs':{str(p):digest(p) for p in ROOT.iterdir() if p.is_file() and p!=final},
        'local_data':{str(p):digest(p) for p in DATA.iterdir() if p.is_file()},
        'local_data_not_a_redistributable_deployment_bundle':True,
        'not_claimed':['model training','neural tokenization/decoding validation','recommendation quality improvement','fresh independent test','public deployment']})
    print({'sealed':True,'assets':verify_receipt(final,GROUPS),'sha256':digest(final),'training_samples':98887,'heldout_events':95885})


if __name__=='__main__':main()
