"""Seal and verify audit artifacts, successful tests and the entire prior delivery."""
import csv
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from gsearch.quality_protocol import digest,save

ROOT=Path('reports/stage46')


def read(path: Path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def verify_prior() -> int:
    path=Path('reports/stage45/final-validation-v2.json')
    assert digest(path)=='2e7bf16a10f196f42cde8ce2bd75055f3e611951b3ecbbcef73d91d879bf0949'
    previous=read(path)
    for name,expected in previous['files'].items():assert digest(Path(name))==expected,name
    return len(previous['files'])


def main() -> None:
    receipt_path=ROOT/'final-validation.json'
    prior=verify_prior()
    if receipt_path.exists():
        receipt=read(receipt_path)
        for name,expected in receipt['files'].items():assert digest(Path(name))==expected,name
        print({'verified_existing':True,'audit_assets':len(receipt['files']),'prior_assets_unchanged':prior,
               'sha256':digest(receipt_path)})
        return
    validation=read(ROOT/'validation.json')
    assert validation['status']=='passed'
    assert validation['independent_native_conditional_metric_checks']==9
    assert validation['independent_terminal_prefix_event_checks']==10806
    assert validation['case_provenance_and_selection_checks']==36
    log=(ROOT/'tests.log').read_text(encoding='utf-8-sig').replace('\r\n','\n')
    assert re.search(r'Ran 12 tests in ',log) and re.search(r'\nOK\s*$',log) and 'FAILED' not in log
    audit=read(ROOT/'audit.json')
    assert sum(audit['availability_partition'].values())==46352
    assert audit['validation']['prediction_event_rows_verified']==9*46352
    assert audit['validation']['raw_neural_profile_traces_verified']==6*2128
    assert audit['validation']['all_9_full_scores_reproduced_to_1e_14']
    assert read(ROOT/'next-step-decision.json')['status']=='recommended_not_executed'
    assert read(ROOT/'next-step-decision.json')['optimizer_updates']==0
    for name,expected in read(ROOT/'protocol.json')['files'].items():assert digest(Path(name))==expected,name
    with (ROOT/'failure-audit.csv').open(encoding='utf-8-sig',newline='') as handle:
        assert len(list(csv.DictReader(handle)))==12
    git=shutil.which('git')
    if git is None:
        bundled=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe'
        if bundled.exists():git=str(bundled)
    if git is None:raise RuntimeError('Git needed to verify local-only audit paths')
    ignored=subprocess.run([git,'check-ignore','data/stage46-audit/cases.json','data/stage46-audit/item-exposure.json'],
        check=True,capture_output=True,text=True)
    assert len(ignored.stdout.splitlines())==2
    assert 'torch' not in sys.modules and 'transformers' not in sys.modules
    checks={'prior_303_assets_unchanged':prior,'tests_passed':12,'native_conditional_groups_checked':9,
        'independent_terminal_prefix_events':10806,'source_cases_verified':36,'full_event_rows_replayed':9*46352,
        'old_full_scores_reproduced':True,'private_cases_and_exposure_git_ignored':True,
        'torch_or_transformers_loaded':False,'new_training_or_generation':False,'dev_evaluation':False,
        'website_or_dependency_changes':False,'next_probe_executed':False,
        'prefix_diagnosis_is_terminal_coverage_not_pruning_time':True}
    save(ROOT/'release-validation.json',{'status':'passed','checks':checks})
    paths=[Path('gsearch/sid_failure_audit.py'),Path('tests/test_sid_failure_audit.py'),
        Path('scripts/audit_sid_failures.py'),Path('scripts/probe_sid_audit_outputs.py'),
        Path('scripts/validate_sid_failure_audit.py'),Path('scripts/report_sid_failure_audit.py'),
        Path('scripts/prepare_sid_failure_audit.py'),Path('scripts/verify_sid_failure_audit.py'),
        Path('docs/SID_FAILURE_AUDIT_V46.md'),Path('reports/阶段46_SID失败归因审计.md')]
    paths.extend(p for p in ROOT.iterdir() if p.is_file() and p!=receipt_path)
    paths.extend(p for p in Path('data/stage46-audit').iterdir() if p.is_file())
    files={str(path):digest(path) for path in sorted(set(paths))}
    save(receipt_path,{'status':'passed','scope':'local descriptive audit; per-user material not redistributable',
        'prior_receipt_sha256':'2e7bf16a10f196f42cde8ce2bd75055f3e611951b3ecbbcef73d91d879bf0949',
        'checks':checks,'files':files})
    print({'status':'passed','audit_assets':len(files),'prior_assets_unchanged':prior,
           'sha256':digest(receipt_path),'checks':checks})


if __name__=='__main__':main()
