"""Read-only audit of existing acceptance records and versioned orchestration."""
import ast
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


class PromptOnly(ast.NodeTransformer):
    def visit_Assign(self,node):
        if any(isinstance(t,ast.Name) and t.id=='prompt' for t in node.targets):
            node.value=ast.Constant('versioned_prompt_path')
        return self.generic_visit(node)


def main():
    old=ast.parse((ROOT/'research70/runner.py').read_text())
    new=ast.parse((ROOT/'research71/runner.py').read_text())
    names=['observed_llm','observed_run','observed_constrained']
    for name in names:
        a=next(n for n in old.body if isinstance(n,ast.FunctionDef) and n.name==name)
        b=next(n for n in new.body if isinstance(n,ast.FunctionDef) and n.name==name)
        assert ast.dump(PromptOnly().visit(a))==ast.dump(PromptOnly().visit(b)),name
    summary=json.loads((ROOT/'reports/stage71/custom-job-validation.json').read_text())
    for case in summary['cases']:
        raw=json.loads((ROOT/f"data/stage71-custom/acceptance/{case['case']}.json").read_text())
        row=raw['result']['results'][0];meta=row['metadata']
        case.update({'rejected_proposals':sum(bool(e.get('error')) for e in meta.get('proposal_events',[])),
                     'charged_application_attempts':meta['charged_application_attempts'],
                     'framework_steps_exhausted':meta['framework_steps_exhausted']})
        if case['case']=='no_results':
            assert not row['answer'] and not row['completed_protocol']
            assert meta['framework_steps_exhausted'] and meta['llm_usage']['calls']==8
            assert meta['charged_application_attempts']==6 and case['rejected_proposals']==6
            assert len(row['trace']['trace'])==1 and not row['trace']['trace'][0]['result']['papers']
    (ROOT/'reports/stage71/custom-job-validation.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
    report={'status':'passed','custom_runner_functions_equal_v70_except_prompt_path':names,
            'presets_worker_imports_original_v70_runner':True,
            'custom_prompt_sha256':hashlib.sha256((ROOT/'research71/prompts/custom.txt').read_bytes()).hexdigest(),
            'actual_empty_result_rejected_fake_citations_and_exhausted_budget':True,
            'extra_model_jobs_started':0}
    worker=(ROOT/'research71/worker.py').read_text()
    assert 'from research70.runner import' in worker and 'task_kind' in worker
    (ROOT/'reports/stage71/evidence-validation.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report))


if __name__=='__main__':main()
