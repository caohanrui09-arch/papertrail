"""Real algorithms/LLM integration without sockets; same native policy implementations."""
from copy import deepcopy
import hashlib,json,time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]

def main():
    import os
    os.chdir(ROOT)
    from gsearch.cold_fusion import load
    from gsearch.unified_session import UnifiedSession
    from gsearch.unified_search import AsOfBM25
    from gsearch.unified_agent import ToolClient,run,load_model
    from gsearch.constrained_agent import GuardedClient
    from gsearch.constrained_agent_isolated import run as constrained
    from research63.server import AuditModel
    from smolagents.default_tools import FinalAnswerTool
    folder=ROOT/'data/stage63-inprocess';folder.mkdir(exist_ok=False)
    report=ROOT/'reports/stage63';report.mkdir(exist_ok=True)
    tasks=json.loads((ROOT/'data/stage19-unified/benchmark/evaluation-tasks.json').read_text())[:3]
    protocol={'date':'2026-11-11','transport':'inprocess UnifiedSession, no sockets; constructor dependency injection only',
        'policies':['fixed','llm_agent','constrained'],'tasks':tasks,'prior_task_reuse':True,
        'common_algorithm':'content','budgets':{'tool_attempts':6,'retrievals':2,'reads':2,'llm_calls':8,'input_tokens':30000,'output_tokens':1280},
        'code':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'research63').glob('*') if p.is_file()}}
    (folder/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf8')
    start=time.perf_counter();algorithm=AuditModel(load());searcher=AsOfBM25(algorithm)
    print(json.dumps({'algorithms_ready':True,'seconds':time.perf_counter()-start}),flush=True)
    from gsearch.expansion_recommendation import signature
    assert signature(algorithm.base)==json.loads((ROOT/'reports/stage13/resource-10000.json').read_text())['model_signature']
    class DirectClient(ToolClient):
        def __init__(self,task,port=0):
            self.session=UnifiedSession(algorithm,searcher,task['user_id'],task['at'],'content',.25)
            self.accepted=self.accepted_input=None
        def call(self,name,**arguments):
            result=self.session.invoke(name,arguments)
            if 'error' in result:raise ValueError(result['error'])
            return result
        def snapshot(self):return self.session.snapshot()
        def close(self):pass
    class DirectGuarded(GuardedClient,DirectClient):pass
    rankings={}
    for task in tasks:
        rankings[task['id']]={}
        for method in ('popular','sar','content','hybrid','cold_aware'):
            alpha=.5 if method=='hybrid' else .25
            rows=algorithm.recommend(task['user_id'],task['at'],method,10,alpha)
            native=algorithm.base.recommend(task['user_id'],task['at'],method,10,alpha)
            assert [r['doc_id'] for r in rows]==[r['doc_id'] for r in native]
            rankings[task['id']][method]=rows
    (folder/'rankings.json').write_text(json.dumps(rankings,ensure_ascii=False,indent=2),encoding='utf8')
    results=[];model=None;baseline=deepcopy(FinalAnswerTool.inputs)
    for task in tasks:
        for policy in protocol['policies']:
            if policy!='fixed' and model is None:
                print('Loading real local Qwen model',flush=True);model=load_model()
            assert FinalAnswerTool.inputs==baseline
            with patch('gsearch.unified_agent.ToolClient',DirectClient),patch('gsearch.constrained_agent_isolated.GuardedClient',DirectGuarded):
                result=constrained(task,model) if policy=='constrained' else run(task,policy,model)
            assert FinalAnswerTool.inputs==baseline
            results.append(result)
            (folder/'results.json').write_text(json.dumps({'complete':False,'results':results},ensure_ascii=False,indent=2),encoding='utf8')
            print(json.dumps({'task':task['id'],'policy':policy,'completed':result['completed_protocol'],'seconds':round(result['seconds'],2)}),flush=True)
    (folder/'results.json').write_text(json.dumps({'complete':True,'results':results},ensure_ascii=False,indent=2),encoding='utf8')
    # Reuse the frozen independent raw-XML scorer; gold is loaded only AFTER all model runs.
    import scripts.score_unified as scorer
    summaries={}
    gold=json.loads((ROOT/'data/stage19-unified/benchmark/evaluation-gold.json').read_text())
    for policy in ('llm_agent','constrained'):
        view=folder/('score-'+policy);(view/'evaluation').mkdir(parents=True)
        (view/'evaluation-tasks.json').write_text(json.dumps(tasks),encoding='utf8')
        (view/'evaluation-gold.json').write_text(json.dumps([r for r in gold if r['id'] in {t['id'] for t in tasks}]),encoding='utf8')
        for result in results:
            if result['policy'] in ('fixed',policy):
                alias='fixed' if result['policy']=='fixed' else 'llm_agent'
                (view/'evaluation'/f"{result['task_id']}-{alias}.json").write_text(json.dumps(result),encoding='utf8')
        scorer.ROOT=view;summaries[policy]=scorer.score('evaluation')
    (folder/'scores.json').write_text(json.dumps(summaries,indent=2),encoding='utf8')
    aggregate={'scope':'three reused controlled tasks; real inprocess run, no new human relevance labels or independent/generalization claim',
        'methods':{'fixed':summaries['llm_agent']['methods']['fixed'],'llm_agent':summaries['llm_agent']['methods']['llm_agent'],'constrained':summaries['constrained']['methods']['llm_agent']},
        'ranking_checks':15,'native_ranking_preserved':True,'native_schema_preserved':True,
        'historical_quality':{name:json.loads((ROOT/f'reports/stage15/{file}-dev.json').read_text())['summary'] for name,file in [('content','content'),('rrf','rrf'),('cold_aware','gated')]},
        'historical_quality_is_new_run':False,'http_validation':False}
    (report/'inprocess-validation.json').write_text(json.dumps(aggregate,indent=2),encoding='utf8')
    searcher.close();print(json.dumps(aggregate['methods']),flush=True)

if __name__=='__main__':main()
