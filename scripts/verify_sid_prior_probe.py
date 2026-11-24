"""Seal the completed frozen512 probe and verify every historical input receipt."""
import csv
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys

from gsearch.quality_protocol import digest,save
from gsearch.sid_prior_probe import ROOT,DATA,read


def verify_files(files: dict) -> None:
    for name,expected in files.items():assert digest(Path(name))==expected,name


def test_log(name: str,count: int) -> None:
    text=(ROOT/name).read_text(encoding='utf-8-sig').replace('\r\n','\n')
    assert re.search(rf'Ran {count} tests in ',text) and re.search(r'\nOK\s*$',text) and 'FAILED' not in text,name


def main() -> None:
    subprocess.run([sys.executable,'-E','-s','-m','scripts.verify_sid_budget_changes'],check=True)
    prior=Path('reports/stage49/final-validation.json')
    assert digest(prior)=='24ee8b881aa9a037d8dbbd75d6a013d53e9d5c4b7384d9952376a048ef3d3f19'
    protocol=read(ROOT/'protocol.json');verify_files(protocol['files'])
    target=ROOT/'final-validation.json'
    if target.exists():
        receipt=read(target);assert receipt['status']=='passed';verify_files(receipt['files'])
        print({'verified_existing':True,'probe_assets':len(receipt['files']),'prior_assets_unchanged':689,'sha256':digest(target)})
        return
    test_log('prior-tests.log',8);test_log('tensor-tests.log',12)
    execution=read(ROOT/'execution.json');validation=read(ROOT/'validation.json')
    assert execution['status']=='complete' and execution['optimizer_updates']==0
    assert execution['beam_requests']==384 and execution['successful_teacher_forced_samples']==192
    assert execution['additional_model_forward_samples']==execution['reused128_inference_requests']==0
    assert validation['status']=='passed'
    for key,expected in {'unchanged_profiles':32,'unchanged_strict_prefixes':32,'beam_requests':384,
        'legal_intermediate_prefixes':19200,'native_ancestry_links':19200,'new_token_positions':960,
        'old128_positions_prior_only_rescored':960,'native_amp_mean_checks':24,'frozen_checkpoints_unchanged':6}.items():
        assert validation[key]==expected,key
    assert validation['old_losses_preserved'] and validation['source_only_two_priors_rebuilt']
    assert len(execution['costs'])==6 and execution['wall_seconds']<protocol['resource_caps']['wall_seconds']
    for row in execution['costs']:
        assert row['in_memory_weights_before_sha256']==row['in_memory_weights_after_sha256']
        assert row['all_gradients_none'] and row['all_parameters_frozen'] and row['digest_window']=='complete A+B'
        assert row['gpu_reserved_peak_bytes']<2.5*2**30 and row['process_peak_bytes']<6*2**30
    summary=read(ROOT/'summary.json');decision=read(ROOT/'decision.json')
    assert not any(decision[k] for k in ['training_started','rl_started','full_tuning_or_dev_rerun','default_changed'])
    beats=[];improves=[];less=[]
    for run in protocol['models']:
        for budget,filename in [(128,'reference128-rescored.json'),(512,'position-loss.json')]:
            records=read(DATA/run/filename)['samples'];semantic=[p for r in records for p in r['positions'][:3]]
            s=summary['runs'][run][str(budget)]['semantic']
            for field,raw in [('conditional_nll','position_conditional_nll'),('prior4096_nll','label4096_position_prior_nll'),
                              ('prior1024_nll','label1024_position_prior_nll'),('full_vocab_nll_fp32','full_vocab_nll')]:
                assert s[field]==statistics.mean(p[raw] for p in semantic)
        old=summary['runs'][run]['128'];new=summary['runs'][run]['512']
        assert old['semantic']['prior4096_nll']==new['semantic']['prior4096_nll']
        if new['semantic']['conditional_nll']<new['semantic']['prior4096_nll']:beats.append(run)
        if new['semantic']['conditional_nll']<old['semantic']['conditional_nll']:improves.append(run)
        if new['history']['jaccard_mean']>old['history']['jaccard_mean']:less.append(run)
    assert decision['semantic_nll_better_than_common4096_marginal_prior_runs']==beats
    assert decision['semantic_nll_better_than128_runs']==improves and decision['mean_jaccard_increased_runs']==less
    for name,count in [('history-comparison.csv',36),('position-comparison.csv',480),('history-paired-changes.csv',192)]:
        with (ROOT/name).open(encoding='utf-8-sig',newline='') as handle:assert len(list(csv.DictReader(handle)))==count,name
    git=shutil.which('git')
    if git is None:
        bundled=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe'
        if bundled.exists():git=str(bundled)
    assert git
    check=subprocess.run([git,'check-ignore',str(DATA/'profiles.json'),str(DATA/'content-42/history-probe.json'),str(DATA/'content-42/position-loss.json')],
        check=True,capture_output=True,text=True)
    assert len(check.stdout.splitlines())==3
    assert 'torch' not in sys.modules and 'transformers' not in sys.modules
    paths=[Path('gsearch/sid_prior_probe.py'),Path('tests/test_sid_prior_probe.py'),Path('docs/SID_PRIOR_PROBE_V50.md'),
        Path('reports/阶段50_冻结512模型历史与频率先验.md')]
    paths.extend(Path('scripts').glob('*sid_prior_probe*.py'))
    paths.extend(p for p in ROOT.rglob('*') if p.is_file() and p!=target)
    paths.extend(p for p in DATA.rglob('*') if p.is_file())
    files={str(p):digest(p) for p in sorted(set(paths))}
    save(target,{'status':'passed','scope':'source-only frozen model health probe; private derivatives local only',
        'prior_receipt_sha256':digest(prior),'checks':{'prior_assets_unchanged':689,'distinct_boundary_tests':20,
            'new_beam_requests':384,'teacher_forced_samples':192,'optimizer_updates':0,
            'native_ancestry_links':19200,'legal_intermediate_prefixes':19200,'new_token_positions':960,
            'old128_positions_prior_only_rescored':960,'native_amp_mean_checks':24,
            'all_six_weights_unchanged':True,'common4096_prior_for_both_budgets':True,
            'dev_or_full_tuning_rerun':False,'rl_started':False,'website_changed':False,'private_outputs_ignored':True},'files':files})
    print({'status':'passed','probe_assets':len(files),'prior_assets_unchanged':689,'sha256':digest(target)},flush=True)


if __name__=='__main__':main()
