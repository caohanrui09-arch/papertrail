"""Seal prefix-prior diagnosis closure and unchanged historic receipt chain."""
import csv
from pathlib import Path
import re
import shutil
import subprocess
import sys

from gsearch.quality_protocol import digest,save
from gsearch.sid_prefix_prior import ROOT,DATA,read


def check_files(files: dict) -> None:
    for name,expected in files.items():assert digest(Path(name))==expected,name


def main() -> None:
    subprocess.run([sys.executable,'-E','-s','-m','scripts.verify_sid_prior_probe'],check=True)
    prior=Path('reports/stage50/final-validation.json')
    assert digest(prior)=='4cdb8b98db5a983b05536b1fd50cc426db7cf3852adbec381a405274e9f56483'
    protocol=read(ROOT/'protocol.json');check_files(protocol['files'])
    target=ROOT/'final-validation.json'
    if target.exists():
        receipt=read(target);assert receipt['status']=='passed';check_files(receipt['files'])
        print({'verified_existing':True,'closure_assets':len(receipt['files']),'prior_assets_unchanged':742,'sha256':digest(target)})
        return
    log=(ROOT/'tests.log').read_text(encoding='utf-8-sig').replace('\r\n','\n')
    assert re.search(r'Ran 10 tests in ',log) and re.search(r'\nOK\s*$',log) and 'FAILED' not in log
    validation=read(ROOT/'validation.json');assert validation['status']=='passed'
    for key,value in {'label_sequences_per_mapping':4096,'prefix_queries_independent_scan':320,
        'observed_context_distributions_normalized':14369,'archived_model_position_losses_checked':1920,
        'wide_position_comparison_records':960,'group_position_aggregate_rows':288,'unchanged_strict_prefixes':32}.items():
        assert validation[key]==value,key
    assert validation['first_position_equals_marginal'] and validation['unseen_context_uniform']
    assert validation['full_position_codebook_matches_model'] and validation['no_model_load_forward_generate']
    comparison=read(ROOT/'comparison.json');decision=read(ROOT/'decision.json')
    assert decision==comparison['decision']
    beats=[name for name,r in comparison['summary'].items() if r['model512_nll']<r['prefix_nll']-1e-12]
    assert decision['model512_runs_beating_prefix_prior']==beats==[]
    assert decision['closure_condition_met'] and decision['training_branch']=='closed_for_current_design'
    assert not any(decision[k] for k in ['new_training_started','new_decode_or_model_forward','rl_started','dev_evaluated','default_changed','personalization_proven'])
    assert read(ROOT/'closure-evidence.json')['branch_status']=='closed_for_current_design'
    with (ROOT/'four-method-comparison.csv').open(encoding='utf-8-sig',newline='') as handle:assert len(list(csv.DictReader(handle)))==288
    assert 'torch' not in sys.modules and 'transformers' not in sys.modules
    git=shutil.which('git')
    if git is None:
        bundled=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe'
        if bundled.exists():git=str(bundled)
    assert git
    ignored=subprocess.run([git,'check-ignore',str(DATA/'content.prefix-counts.json'),str(DATA/'content.queries.jsonl'),str(DATA/'content-42.comparison.jsonl')],
        check=True,capture_output=True,text=True)
    assert len(ignored.stdout.splitlines())==3
    paths=[Path('gsearch/sid_prefix_prior.py'),Path('tests/test_sid_prefix_prior.py'),Path('docs/SID_PREFIX_PRIOR_V51.md'),
        Path('docs/SID_EXPERIMENT_CLOSURE_V51.md'),Path('reports/阶段51_SID前缀先验与诊断收尾.md')]
    paths.extend(Path('scripts').glob('*sid_prefix_prior*.py'))
    paths.extend(p for p in ROOT.rglob('*') if p.is_file() and p!=target)
    paths.extend(p for p in DATA.rglob('*') if p.is_file())
    files={str(p):digest(p) for p in sorted(set(paths))}
    save(target,{'status':'passed','scope':'offline prefix-frequency diagnostic closure; private derivatives local only',
        'prior_receipt_sha256':digest(prior),'checks':{'prior_assets_unchanged':742,'boundary_tests':10,
            'source_labels_per_mapping':4096,'independently_scanned_queries':320,'normalized_observed_contexts':14369,
            'archived_model_losses_preserved':1920,'comparison_records':960,'aggregate_rows':288,
            'new_training_or_model_forward_or_decoding':False,'budget_escalation_closed':True,
            'resume_evidence_delivered':True,'private_outputs_ignored':True,'personalization_claim':False},'files':files})
    print({'status':'passed','closure_assets':len(files),'prior_assets_unchanged':742,'sha256':digest(target)},flush=True)


if __name__=='__main__':main()
