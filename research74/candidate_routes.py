"""Bounded display/diagnostic routes. Never calls a session tool or model."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

from fastapi import HTTPException,Query
from pydantic import BaseModel,ConfigDict,Field

from research71.custom_tasks import CustomRun
from research70.event_stream import available


class DiagnosticRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    plan_id:str=Field(min_length=36,max_length=36)
    executed_query:str=Field(max_length=2000)
    reviewed:bool
    conditions_reviewed:bool


class PresetDiagnostic(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    task_id:str


def register(app,model,custom,presets,jobs,lock,root: Path):
    from gsearch.unified_search import AsOfBM25
    from research72.evidence import CandidateEvidence
    from research74.diagnostics import QueryDiagnostics
    search=AsOfBM25(model,max_snapshots=1);evidence=CandidateEvidence(model,search)
    diagnostics=QueryDiagnostics(model,search,evidence,root);diagnostic_count=0

    def diagnostic(task,context):
        nonlocal diagnostic_count
        if diagnostic_count>=64:raise HTTPException(429,'64 diagnostic runs per service; records retained')
        diagnostic_count+=1
        return diagnostics.run(task,context)

    @app.post('/lab/v72/diagnostics/custom')
    def custom_diagnostic(body:DiagnosticRequest):
        with lock:
            task,context=custom.resolve(CustomRun(**body.model_dump(),policy='constrained'))
            context.pop('policy',None)
            return diagnostic(task,context)

    @app.post('/lab/v72/diagnostics/preset')
    def preset_diagnostic(body:PresetDiagnostic):
        if body.task_id not in presets:raise HTTPException(422,'Unknown frozen preset')
        with lock:return diagnostic(presets[body.task_id],{'kind':'frozen_preset','task_id':body.task_id})

    def result_view(task,row,events,source):
        start=time.perf_counter();value=evidence.build(task,row,events,source)
        value['evidence_seconds']=time.perf_counter()-start;value['extra_model_calls']=0
        return value

    @app.get('/lab/v72/jobs/{ident}/candidates')
    def job_candidates(ident:str,run_index:int=Query(0,ge=0,le=8)):
        with lock:
            if ident not in jobs:raise HTTPException(404,'Unknown job')
            job=jobs[ident];base=job['folder'];spec=json.loads((base/'input.json').read_text())
            if run_index>=len(spec['tasks'])*len(spec['policies']):raise HTTPException(404,'Unknown run')
            task=spec['tasks'][run_index//len(spec['policies'])]
            events,_=available(base/'events.jsonl');events=[e for e in events if e.get('run_index')==run_index]
            path=base/'result.json';value=None
            try:value=json.loads(path.read_text()) if path.exists() else None
            except json.JSONDecodeError:pass
            rows=(value or {}).get('results',[])
            authoritative=run_index<len(rows)
            row=rows[run_index] if authoritative else {'_in_progress':True,'trace':{'trace':[e['payload'] for e in events if e['kind']=='tool_returned']}}
            source={'kind':'job','job_id':ident,'run_index':run_index,'authoritative_trace':authoritative,
                    'last_event_id':events[-1]['id'] if events else 0}
            if authoritative:source['result_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
            result=result_view(task,row,events,source)
            saved=base/f'candidate-evidence-{run_index}.json'
            if authoritative and (value or {}).get('complete') and job['process'].poll() is not None and not saved.exists():
                temporary=saved.with_suffix('.tmp')
                temporary.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
                temporary.replace(saved)
            return result

    @app.get('/lab/v72/examples/{key}/candidates')
    def example_candidates(key:str):
        if key not in ('fixed','constrained','llm_agent'):raise HTTPException(404,'Unknown retained example')
        path=root/f'data/stage64-http/{key}-http-result.json';row=json.loads(path.read_text())['result']['results'][0]
        with lock:return result_view(presets[row['task_id']],row,[],{'kind':'historical_v64','id':key,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})

    retained={}
    for case in json.loads((root/'reports/stage71/final-validation.json').read_text())['real_custom_model_cases']:
        base=root/'data/stage71-custom/jobs'/case['job_id']
        if (base/'result.json').exists():retained[case['case']]={'case':case,'base':base}

    def retained_data(key):
        if key not in retained:raise HTTPException(404,'Unknown retained v71 case')
        base=retained[key]['base'];spec=json.loads((base/'input.json').read_text());result=json.loads((base/'result.json').read_text())
        return base,spec,result

    @app.get('/lab/v72/retained')
    def retained_list():return {'items':[{'id':key,'label':'阶段71 · '+key+(' · 未提交' if not item['case']['completed_protocol'] else ' · 已提交')} for key,item in retained.items()],
        'scope':'retained integration cases, not independent relevance evaluation; no execution on load'}

    @app.get('/lab/v72/retained/{key}')
    def retained_result(key:str):
        base,spec,result=retained_data(key);value=deepcopy(result)
        for row in value['results']:
            meta=row.get('metadata',{});meta.pop('unverified_model_final',None)
            meta['steps']=[{k:s[k] for k in ('step_number','timing','tool_calls','error','token_usage','is_final_answer') if k in s} for s in meta.get('steps',[]) if 'step_number' in s]
        return {'result':value,'task_context':spec['task_context'],'source_sha256':hashlib.sha256((base/'result.json').read_bytes()).hexdigest()}

    @app.get('/lab/v72/retained/{key}/candidates')
    def retained_candidates(key:str):
        base,spec,result=retained_data(key);events,_=available(base/'events.jsonl')
        with lock:return result_view(spec['tasks'][0],result['results'][0],events,{'kind':'historical_v71','id':key,'sha256':hashlib.sha256((base/'result.json').read_bytes()).hexdigest()})
