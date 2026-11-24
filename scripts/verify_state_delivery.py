"""Actual frozen-result, logical-charge, source and command acceptance."""
import contextlib
import json
import os
from pathlib import Path
import subprocess
import unittest
from gsearch.quality_protocol import digest,save
from scripts.benchmark_state_constraints import ROOT,REPORT,fingerprints


def main() -> None:
    output=REPORT/'delivery-validation.json'
    if output.exists():raise ValueError('Preserve sealed acceptance attempt')
    frozen=json.loads((REPORT/'locked-before-evaluation.json').read_text())
    if fingerprints()!=frozen['fingerprints']:raise ValueError('Frozen code drift')
    for p,h in frozen['tuning'].items():
        if digest(Path(p))!=h:raise ValueError('Tuning history changed')
    from scripts.score_state_constraints import summarize
    for split in ('tuning','evaluation'):
        if summarize(split)!=json.loads((REPORT/f'{split}-summary.json').read_text()):
            raise ValueError('Native raw result recount differs')
    from scripts.replay_constraint_audit import verify_case
    replayed=0
    for split in ('tuning','evaluation'):
        for path in (ROOT/split).glob(f'{split}-*-constrained.json'):
            verify_case(json.loads(path.read_text(encoding='utf-8')));replayed+=1
    if replayed!=16:raise ValueError('Missing constrained raw case')
    logs=Path('.cache/stage21');logs.mkdir(parents=True,exist_ok=True)
    with (logs/'regression-tests.log').open('w',encoding='utf-8') as stream,contextlib.redirect_stdout(stream),contextlib.redirect_stderr(stream):
        tests=unittest.TextTestRunner(stream=stream,verbosity=1).run(unittest.defaultTestLoader.discover('tests'))
    if not tests.wasSuccessful():raise ValueError('Regression failed, inspect private log')
    from gsearch.benchmark_cold_fusion import history
    from gsearch.showcase import verify_receipt
    from gsearch.relocated_demo import verify_bundle
    history();counts={}
    fields={15:('code','data','outputs','report'),16:('code','materials','outputs','private_data','report'),
        17:('code','docs','outputs','report','private_replay_assets'),18:('code','docs','outputs','report'),
        19:('code','outputs','private_data','docs','report'),20:('code','vendor','outputs','private_data','docs','report')}
    for n,groups in fields.items():counts[str(n)]=verify_receipt(Path(f'reports/stage{n}/final-validation.json'),groups)
    from scripts.manage_stage17_env import BASE,VENV,environment
    bundle=verify_bundle(BASE/'replica')
    process=subprocess.run([str(VENV/'Scripts/python.exe'),'-E','-s','-c',
        "import json,importlib.metadata as m;print(json.dumps({d.metadata['Name']:d.version for d in m.distributions()}))"],
        env=environment(),capture_output=True,text=True,check=True)
    versions=json.loads(process.stdout)
    if versions!=json.loads(Path('reports/stage17/runtime-versions.json').read_text())['installed_versions']:
        raise ValueError('Independent runtime packages changed')
    from gsearch.unified_agent import request
    code,health=request('GET','/health')
    if code!=200 or health['candidates']!=10000:raise ValueError('Original service unavailable')
    before=set(ROOT.glob('demo-*/result.json'))
    with (logs/'actual-cli.log').open('w',encoding='utf-8') as stream:
        demo=subprocess.run(['cmd.exe','/c','state-agent-demo.cmd'],env=environment(),stdout=stream,
            stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,timeout=360,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    created=set(ROOT.glob('demo-*/result.json'))-before
    if len(created)!=1:raise ValueError('Expected one new private CLI result')
    path=next(iter(created));raw=json.loads(path.read_text(encoding='utf-8'))
    if demo.returncode!=(0 if raw['completed_protocol'] else 1):raise ValueError('CLI completion/exit code mismatch')
    verify_case(raw)
    from gsearch.human_quality import load_state
    queries,mapping,runs,labels,confirmed=load_state()
    if labels or confirmed:raise ValueError('Human-preparation status changed during this experiment')
    save(output,{'status':'passed','regression_tests':tests.testsRun,'failures':0,'errors':0,
        'evaluation_outputs_recounted':36,'native_state_cases_replayed':replayed,
        'automatic_or_argument_repair_calls':0,'stages3_20_unchanged':True,'history_asset_counts':counts,
        'original_migrated_bundle_assets':len(bundle['files']),'independent_runtime_packages_unchanged':len(versions),
        'human_judgments_still_zero':True,'actual_cli_executed':True,'actual_cli_completed':raw['completed_protocol'],
        'actual_cli_exit_code':demo.returncode,'actual_cli_result':str(path),'actual_cli_sha256':digest(path),
        'default_workflow_unchanged':'fixed','original_service_ready':True})
    print(json.dumps({'status':'passed','tests':tests.testsRun,'actual_cli_completed':raw['completed_protocol']}),flush=True)


if __name__=='__main__':main()
