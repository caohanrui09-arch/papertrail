"""Final seal of the local budget comparison and unchanged historical artifacts."""
from pathlib import Path
import csv
import re
import shutil
import statistics
import subprocess
import sys

from gsearch.quality_protocol import digest, save
from gsearch.sid_budget import ROOT, DATA, RUNS, SEEDS, ARMS, read


def verify_files(files: dict) -> None:
    for name,expected in files.items(): assert digest(Path(name))==expected,name


def main() -> None:
    subprocess.run([sys.executable,'-E','-s','-m','scripts.verify_sid_health_probe'],check=True)
    assert digest(Path('reports/stage47/final-validation.json'))=='3a08654ddb43d8600c4f8fb0966d8663e58569e6003474b3d1ba5cfcc4d08869'
    protocol=read(ROOT/'protocol.json'); verify_files(protocol['files'])
    target=ROOT/'final-validation.json'
    if target.exists():
        receipt=read(target); assert receipt['status']=='passed'; verify_files(receipt['files'])
        print({'verified_existing':True,'budget_assets':len(receipt['files']),'prior_assets_unchanged':399,'sha256':digest(target)})
        return
    log=(ROOT/'tests.log').read_text(encoding='utf-8-sig').replace('\r\n','\n')
    assert re.search(r'Ran 7 tests in ',log) and re.search(r'\nOK\s*$',log) and 'FAILED' not in log
    validation=read(ROOT/'validation.json'); assert validation['status']=='passed'
    environments=read(ROOT/'environment-validation.json')
    assert environments['status']=='passed'
    assert {k:v['count'] for k,v in environments['environments'].items()}=={'cpu':57,'gpu':38,'web':26}
    assert validation['reconstructed_training_token_rows']==8192
    assert validation['full_prediction_event_rows']==6*46352
    assert validation['unique_profile_neural_paths']==6*2128*10
    assert validation['reference128_runs']==validation['native_scorer_slices']==6
    assert validation['native_scorer_slice_events_each']==512
    assert validation['cold_user_fallback_unchanged']
    lock=read(ROOT/'run-lock.json')
    assert lock['frozen_before_first_step129'] and lock['resource_and_reference_preflight_passed']
    assert lock['protocol_sha256']==digest(ROOT/'protocol.json')
    assert lock['preflight_gate_sha256']==digest(RUNS/'content-42/reference128-gate.json')
    for seed in SEEDS:
        for arm in ARMS:
            name=arm+'-'+str(seed); output=RUNS/name
            # Native serialization is also byte-identical in these repeated128 runs.
            assert digest(output/'checkpoint-128/model.safetensors')==digest(Path('runs/stage45')/name/'final/model.safetensors')
            assert read(output/'reference128-gate.json')['all_tensors_bitwise_equal']
            for step in [128,512]: verify_files(read(output/('checkpoint-'+str(step)+'-receipt.json'))['files'])
            assert read(ROOT/(name+'.tuning.score.json'))['native512_slice_exact']
    decision=read(ROOT/'decision.json')
    assert not any(decision[k] for k in ['next_training_started','default_changed','rl_started','dev_evaluated'])
    summary=read(ROOT/'summary.json'); results=read(ROOT/'tuning-results.json')
    for arm in ARMS:
        for step in [128,512]:
            report=Path('reports/stage45') if step==128 else ROOT
            for metric in ['ndcg@10','recall@10']:
                values=[read(report/(arm+'-'+str(s)+'.tuning.score.json'))['user_macro'][metric] for s in SEEDS]
                assert summary['metrics'][arm][str(step)][metric]=={'mean':statistics.mean(values),'sample_sd':statistics.stdev(values)}
        expected=[read(ROOT/(arm+'-'+str(s)+'.tuning.score.json'))['user_macro']['ndcg@10']-
                  read(Path('reports/stage45')/(arm+'-'+str(s)+'.tuning.score.json'))['user_macro']['ndcg@10'] for s in SEEDS]
        assert summary['budget_deltas'][arm]==results['budget_ndcg_deltas_512_minus128'][arm]==expected
    assert summary['decision']==decision
    for name,count in [('quality-comparison.csv',15),('group-comparison.csv',72),('loss-curves.csv',240),
                       ('resource-comparison.csv',12),('output-concentration.csv',12)]:
        with (ROOT/name).open(encoding='utf-8-sig',newline='') as handle: assert len(list(csv.DictReader(handle)))==count,name
    git=shutil.which('git')
    if git is None:
        bundled=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe'
        if bundled.exists(): git=str(bundled)
    assert git
    ignored=subprocess.run([git,'check-ignore',str(DATA/'content.ordered.jsonl'),str(RUNS/'content-42/checkpoint-512/model.safetensors')],
        check=True,capture_output=True,text=True)
    assert len(ignored.stdout.splitlines())==2
    assert 'torch' not in sys.modules and 'transformers' not in sys.modules
    paths=[Path('gsearch/sid_budget.py'),Path('tests/test_sid_budget.py'),Path('docs/SID_BUDGET_V48.md'),
           Path('reports/阶段48_受控训练预算对照.md')]
    paths.extend(Path('scripts').glob('*sid_budget*.py'))
    paths.extend(p for p in ROOT.rglob('*') if p.is_file() and p!=target)
    paths.extend(p for p in DATA.rglob('*') if p.is_file())
    paths.extend(p for p in RUNS.rglob('*') if p.is_file())
    files={str(p):digest(p) for p in sorted(set(paths))}
    save(target,{'status':'passed','scope':'local descriptive budget+exposure comparison; no redistribution of private derivatives',
        'prior_receipt_sha256':digest(Path('reports/stage47/final-validation.json')),
        'checks':{'prior_assets_unchanged':399,'boundary_tests':7,'exact128_reference_runs':6,
            'reconstructed_token_rows':8192,'full_prediction_rows':278112,'legal_unique_neural_paths':127680,
            'native512_event_scoring_checks':6,'new_training_runs':6,'steps_per_run':512,
            'checkpoints_per_run':[128,512],'dev_evaluated':False,'rl_started':False,'default_changed':False,
            'private_outputs_ignored':True,'environments_unchanged':{'cpu':57,'gpu':38,'web':26}},'files':files})
    print({'status':'passed','budget_assets':len(files),'prior_assets_unchanged':399,'sha256':digest(target)},flush=True)


if __name__=='__main__': main()
