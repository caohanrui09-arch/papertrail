"""Reuse v1 harness with versioned outputs and native schema invariance guards."""
from copy import deepcopy
import json
from pathlib import Path
from gsearch.quality_protocol import save,digest
from gsearch.constrained_agent_isolated import run as isolated_run
from scripts import benchmark_state_constraints as base

ROOT=Path('data/stage21-isolated')
REPORT=Path('reports/stage21-isolated')
EXTRA=['gsearch/schema_isolation.py','gsearch/constrained_agent_isolated.py',
    'scripts/benchmark_isolated_constraints.py','scripts/run_isolated_trial.py',
    'scripts/score_isolated_constraints.py','tests/test_schema_isolation.py']


def configure() -> None:
    from smolagents.default_tools import FinalAnswerTool
    baseline=deepcopy(FinalAnswerTool.inputs)
    if baseline['answer']['type']!='any':raise ValueError('Start a fresh process with original native default schema')
    base.ROOT=ROOT;base.REPORT=REPORT;base.CODE=base.CODE+EXTRA
    original_run=base.run
    def assert_clean() -> None:
        if FinalAnswerTool.inputs!=baseline:raise ValueError('Cross-policy native class schema contamination')
    def original(task,policy,model):
        assert_clean();result=original_run(task,policy,model);assert_clean()
        result['metadata']['native_default_schema_unchanged']=True
        return result
    def constrained(task,model):
        assert_clean();result=isolated_run(task,model);assert_clean()
        return result
    base.run=original;base.run_constrained=constrained


def fingerprints() -> dict:
    base.ROOT=ROOT;base.REPORT=REPORT
    old_code=base.CODE
    try:
        base.CODE=list(dict.fromkeys(old_code+EXTRA))
        return base.fingerprints()
    finally:base.CODE=old_code


def main() -> None:
    import sys
    configure();base.main()
    if '--phase' in sys.argv and sys.argv[sys.argv.index('--phase')+1]=='prepare':
        path=REPORT/'evaluation-plan.json';plan=json.loads(path.read_text())
        old=json.loads(Path('reports/stage21/evaluation-plan.json').read_text())
        if plan['budgets']!=old['budgets'] or plan['thresholds']!=old['thresholds']:raise ValueError('Bug fix must not change selection gates')
        plan.update(version='isolated-v2',repair_only='Deep-copy per-instance tool input schemas before mutation; assert native defaults before/after every policy',
            invalid_v1_notice_sha256=digest(Path('reports/stage21/INVALIDATED_SCHEMA_CONTAMINATION.json')),
            terminal_logging='driver redirects worker output to a private file; model budgets and protocol unchanged')
        save(path,plan)


if __name__=='__main__':main()
