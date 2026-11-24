"""Seal verified audit evidence and the unchanged model/website receipt chain."""
import csv
from pathlib import Path
import re
import shutil
import subprocess
import sys

from gsearch.quality_protocol import digest,save
from gsearch.sid_budget_audit import ROOT,DATA,read


def verify_files(files: dict) -> None:
    for name,expected in files.items():assert digest(Path(name))==expected,name


def main() -> None:
    subprocess.run([sys.executable,'-E','-s','-m','scripts.verify_sid_budget'],check=True)
    prior=Path('reports/stage48/final-validation.json')
    assert digest(prior)=='7de4e3e0b259fbac26288b547304a060c3de8b9cbb221e6584190117532f144c'
    protocol=read(ROOT/'protocol.json');verify_files(protocol['files'])
    target=ROOT/'final-validation.json'
    if target.exists():
        receipt=read(target);assert receipt['status']=='passed';verify_files(receipt['files'])
        print({'verified_existing':True,'audit_assets':len(receipt['files']),'prior_assets_unchanged':648,'sha256':digest(target)})
        return
    text=(ROOT/'tests.log').read_text(encoding='utf-8-sig').replace('\r\n','\n')
    assert re.search(r'Ran 12 tests in ',text) and re.search(r'\nOK\s*$',text) and 'FAILED' not in text
    validation=read(ROOT/'validation.json');assert validation['status']=='passed'
    for key,expected in {'source_item_counts':9000,'source_exposure_samples':4096,'paired_full_event_checks':278112,
        'independent_terminal_prefix_checks':21612,'native_conditional_metric_checks':12,
        'changed_event_records_verified':59,'case_selection_and_v1_metadata_checks':22,'unchanged_stage48_output_summaries':12}.items():
        assert validation[key]==expected,key
    source=Path('scripts/validate_sid_budget_changes.py').read_text(encoding='utf-8')
    for old,new in [('for group,counts in cohorts.items():','for bucket_key,counts in cohorts.items():'),
        ("actual=result['changes'][group]","actual=result['changes'][bucket_key]"),
        ('deltas[group]','deltas[bucket_key]'),('positive[group]','positive[bucket_key]'),('negative[group]','negative[bucket_key]')]:
        assert source.count(old)==1;source=source.replace(old,new)
    assert source==Path('scripts/validate_sid_budget_changes_v2.py').read_text(encoding='utf-8')
    audit=read(ROOT/'audit.json');decision=read(ROOT/'decision.json')
    assert audit['no_model_load_fit_generate'] and not audit['dev_evaluated'] and not audit['rl_started']
    assert not any(decision[k] for k in ['new_training_started','generation_started','rl_started','dev_evaluated','default_changed'])
    assert decision['recommended_next_not_executed']
    for run,r in audit['runs'].items():
        full=r['changes']['full']
        assert sum(full['transitions'].values())==46352
        numerator=r['changes']['exposure:newly_labelled_1025_4096']['gross_positive_ndcg']
        expected=numerator/full['gross_positive_ndcg'] if full['gross_positive_ndcg'] else None
        assert decision['newly_labelled_gross_positive_shares'][run]==expected
    threshold=sum((decision['newly_labelled_gross_positive_shares']['content-'+str(s)] or 0)>.5 for s in [42,2024,3407])
    assert threshold==decision['content_seeds_meeting_threshold']==0
    assert not decision['fixed1024_repeat4_vs4096_singlepass_priority_triggered']
    with (ROOT/'audit-table.csv').open(encoding='utf-8-sig',newline='') as handle:assert len(list(csv.DictReader(handle)))==6
    git=shutil.which('git')
    if git is None:
        bundled=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe'
        if bundled.exists():git=str(bundled)
    assert git
    result=subprocess.run([git,'check-ignore',str(DATA/'cases.json'),str(DATA/'item-exposure.json'),str(DATA/'content-42.changes.jsonl')],
        check=True,capture_output=True,text=True)
    assert len(result.stdout.splitlines())==3
    assert 'torch' not in sys.modules and 'transformers' not in sys.modules
    paths=[Path('gsearch/sid_budget_audit.py'),Path('tests/test_sid_budget_audit.py'),Path('docs/SID_BUDGET_AUDIT_V49.md'),
           Path('reports/阶段49_512步收益与集中度审计.md')]
    paths.extend(Path('scripts').glob('*sid_budget_changes*.py'))
    paths.extend(p for p in ROOT.rglob('*') if p.is_file() and p!=target)
    paths.extend(p for p in DATA.rglob('*') if p.is_file())
    files={str(p):digest(p) for p in sorted(set(paths))}
    save(target,{'status':'passed','scope':'offline descriptive audit; private derivatives are local only',
        'prior_receipt_sha256':digest(prior),'checks':{'prior_assets_unchanged':648,'boundary_tests':12,
            'native_full_scores_reproduced':12,'native_conditional_checks':12,'paired_events':278112,
            'terminal_prefix_checks':21612,'changed_event_records':59,'verified_cases':22,
            'corrected_validator_only_renames_loop_variable':True,'private_outputs_ignored':True,
            'new_training_or_generation':False,'dev_evaluated':False,'rl_started':False},'files':files})
    print({'status':'passed','audit_assets':len(files),'prior_assets_unchanged':648,'sha256':digest(target)},flush=True)


if __name__=='__main__':main()
