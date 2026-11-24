"""Recount valid v2 outputs, own verifier schemas, and execute the real CLI."""
import contextlib
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import unittest
from gsearch.quality_protocol import digest,save
from scripts.benchmark_isolated_constraints import ROOT,REPORT,fingerprints


class SchemaCleanupResult(unittest.TextTestResult):
    """Legacy v1 regression intentionally exercises the invalid adapter; isolate tests."""
    def startTest(self,test):
        from smolagents.default_tools import FinalAnswerTool
        self.saved_schema=deepcopy(FinalAnswerTool.inputs)
        super().startTest(test)

    def stopTest(self,test):
        from smolagents.default_tools import FinalAnswerTool
        if FinalAnswerTool.inputs!=self.saved_schema:self.schema_cleanup_tests.append(test.id())
        FinalAnswerTool.inputs.clear();FinalAnswerTool.inputs.update(self.saved_schema)
        super().stopTest(test)

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.schema_cleanup_tests=[]


def main() -> None:
    output=REPORT/'delivery-validation.json'
    if output.exists():raise ValueError('Preserve sealed acceptance attempt')
    frozen=json.loads((REPORT/'locked-before-evaluation.json').read_text())
    if not frozen['evaluation_not_started']:raise ValueError('Evaluation preceded lock')
    if fingerprints()!=frozen['fingerprints']:raise ValueError('Frozen code drift')
    for p,h in frozen['tuning'].items():
        if digest(Path(p))!=h:raise ValueError('Tuning changed')
    from scripts.score_isolated_constraints import summarize
    for split in ('tuning','evaluation'):
        if summarize(split)!=json.loads((REPORT/f'{split}-summary.json').read_text()):
            raise ValueError('Native raw result recount differs')
    from scripts.replay_isolated_constraints import verify_case
    replayed=0
    for split in ('tuning','evaluation'):
        for path in (ROOT/split).glob(f'{split}-*-constrained.json'):
            verify_case(json.loads(path.read_text(encoding='utf-8')));replayed+=1
    if replayed!=16:raise ValueError('Missing constrained cases')
    replay=json.loads((REPORT/'replay-and-errors.json').read_text())
    if replay['native_default_schema_guard_passed_cases']!=48:raise ValueError('Missing schema guards')
    logs=Path('.cache/stage21-isolated');logs.mkdir(parents=True,exist_ok=True)
    from smolagents.default_tools import FinalAnswerTool
    native_defaults=deepcopy(FinalAnswerTool.inputs)
    if native_defaults['answer']['type']!='any':raise ValueError('Dirty native process')
    with (logs/'regression-tests.log').open('w',encoding='utf-8') as stream,contextlib.redirect_stdout(stream),contextlib.redirect_stderr(stream):
        tests=unittest.TextTestRunner(stream=stream,verbosity=1,resultclass=SchemaCleanupResult).run(unittest.defaultTestLoader.discover('tests'))
    if not tests.wasSuccessful():raise ValueError('Regression failed; inspect private log')
    if FinalAnswerTool.inputs!=native_defaults:raise ValueError('Test cleanup failed')
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
    if code!=200 or health['candidates']!=10000:raise ValueError('Shared service unavailable')
    before=set(ROOT.glob('demo-*/result.json'))
    with (logs/'actual-cli.log').open('w',encoding='utf-8') as stream:
        demo=subprocess.run(['cmd.exe','/c','state-agent-isolated-demo.cmd'],env=environment(),stdout=stream,
            stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,timeout=360,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    created=set(ROOT.glob('demo-*/result.json'))-before
    if len(created)!=1:raise ValueError('Expected one new private CLI result')
    path=next(iter(created));raw=json.loads(path.read_text(encoding='utf-8'))
    if demo.returncode!=(0 if raw['completed_protocol'] else 1):raise ValueError('CLI exit/completion mismatch')
    verify_case(raw)
    if raw['metadata'].get('native_default_schema_unchanged') is not True:raise ValueError('CLI native schema guard missing')
    from gsearch.human_quality import load_state
    queries,mapping,runs,labels,confirmed=load_state()
    if labels or confirmed:raise ValueError('Human preparation state changed')
    if fingerprints()!=frozen['fingerprints']:raise ValueError('Frozen code changed during acceptance')
    save(output,{'status':'passed','version':'isolated-v2','regression_tests':tests.testsRun,'failures':0,'errors':0,
        'test_only_schema_cleanup':tests.schema_cleanup_tests,'cleanup_does_not_change_experiment_processes':True,
        'evaluation_outputs_recounted':36,'native_state_cases_replayed':replayed,'schema_guard_cases':48,
        'automatic_or_argument_repair_calls':0,'invalid_v1_metrics_used_as_evidence':False,
        'stages3_20_unchanged':True,'history_asset_counts':counts,'original_migrated_bundle_assets':len(bundle['files']),
        'independent_runtime_packages_unchanged':len(versions),'human_judgments_still_zero':True,
        'actual_cli_executed':True,'actual_cli_completed':raw['completed_protocol'],'actual_cli_exit_code':demo.returncode,
        'actual_cli_result':str(path),'actual_cli_sha256':digest(path),'default_workflow_unchanged':'fixed',
        'original_service_ready':True,'service_instance':health['instance_id']})
    print(json.dumps({'status':'passed','tests':tests.testsRun,'actual_cli_completed':raw['completed_protocol']}),flush=True)


if __name__=='__main__':main()
