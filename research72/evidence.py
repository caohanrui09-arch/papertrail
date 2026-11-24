"""Read-only evidence from actual native traces, never a tool response to the Agent."""
import re
from typing import Any


STOP={'a','an','the','is','are','of','to','in','and','or','that','with','for','by'}


def expression(query: str) -> str:
    """Same bounded literal-OR adapter as frozen AsOfBM25; SQLite owns analysis."""
    words=list(dict.fromkeys(re.findall(r'\w+',query.casefold())))[:128]
    return ' OR '.join('"'+word+'"' for word in words if word not in STOP)


class CandidateEvidence:
    def __init__(self,model: Any,search: Any):
        self.model=model;self.search=search

    def metadata(self,doc: str) -> dict:
        row=self.model.by_id[doc]
        return {k:row[k] for k in ('doc_id','title','version','version_key','source_url','published_at','available_at')}

    def search_details(self,at: str,query: str,doc: str) -> dict:
        exp=expression(query)
        if not exp:return {'matched_title_terms':[],'matched_abstract_terms':[],'native_bm25_score':None}
        left,right='⟦PT72⟧','⟦/PT72⟧'
        with self.search.lock:
            db,_=self.search._snapshot(at)
            row=db.execute('SELECT highlight(docs,1,?,?),highlight(docs,2,?,?),bm25(docs,0,2,1) '
                           'FROM docs WHERE docs MATCH ? AND doc_id=?',(left,right,left,right,exp,doc)).fetchone()
        if row is None:return {'matched_title_terms':[],'matched_abstract_terms':[],'native_bm25_score':None}
        terms=lambda text:list(dict.fromkeys(re.findall(re.escape(left)+'(.*?)'+re.escape(right),text,re.S)))
        return {'matched_title_terms':terms(row[0]),'matched_abstract_terms':terms(row[1]),
                'native_bm25_score':-row[2],'method':'SQLite FTS5 native highlight and bm25; surface forms, not per-term score contributions'}

    def build(self,task: dict,row: dict,events: list[dict],source: dict) -> dict:
        trace=(row.get('trace') or {}).get('trace',[]);papers={};retrievals=[]
        requested={e['payload'].get('arguments',{}).get('doc_id') for e in events if e['kind']=='tool_requested' and e['payload'].get('tool')=='read_paper'}
        requested.update(e.get('arguments',{}).get('doc_id') for e in trace if e['tool']=='read_paper')
        requested.update(e.get('arguments',{}).get('doc_id') for e in row.get('metadata',{}).get('wire_attempts',[]) if e.get('name')=='read_paper')
        reads={e['result']['doc_id']:e for e in trace if e['tool']=='read_paper' and not e['result'].get('error')}
        accepted=row.get('answer') if row.get('completed_protocol') else None
        if row.get('_in_progress'):
            accepted=next((e['result'] for e in reversed(trace) if e['tool']=='finalize' and not e['result'].get('error')),None)
        cited={p['doc_id'] for p in (accepted or {}).get('citations',[])}
        for entry in trace:
            tool=entry['tool'];result=entry['result']
            if tool not in ('search_papers','recommend_papers'):continue
            retrievals.append({'attempt':entry['attempt'],'tool':tool,'arguments':entry['arguments'],
                               'error':result.get('error'),'count':len(result.get('papers',[])),
                               'method':result.get('method'),'as_of':result.get('as_of'),'seconds':entry['seconds']})
            if result.get('error'):continue
            for rank,paper in enumerate(result.get('papers',[]),1):
                doc=paper['doc_id']
                if doc not in self.model.by_id:continue
                if doc not in papers:papers[doc]={**self.metadata(doc),'occurrences':[]}
                extra={}
                if tool=='search_papers':extra=self.search_details(task['at'],entry['arguments']['query'],doc)
                else:
                    evidence=paper.get('algorithm_evidence') or {}
                    cold=evidence.get('profile_kind')=='cold_user_popularity_fallback' or result.get('cold_user_fallback',False)
                    extra={'profile_cosine':None if cold else evidence.get('content_score'),
                           'nearest_history_paper':evidence.get('nearest_history_paper'),
                           'cold_user_fallback':cold,'fallback_reason':'无可用历史画像，原生流行度回退' if cold else None,
                           'native_algorithm_evidence':evidence}
                papers[doc]['occurrences'].append({'tool':tool,'attempt':entry['attempt'],'rank':rank,
                    'method':result.get('method'),'native_score':paper.get('score') if tool=='search_papers' else (paper.get('algorithm_evidence') or {}).get('selected_score'),
                    'score_note':'不同方法的原始分数不可直接比较','evidence':extra,'source_paper':paper})
        for doc,paper in papers.items():
            paper.update({'selected_for_read':doc in requested,'read_success':doc in reads,'cited':doc in cited,
                          'read_attempt':reads.get(doc,{}).get('attempt'),
                          'selection_definition':'仅表示已观察到读取请求；未选中不等于不相关',
                          'metadata_source':'frozen catalog; added for display, not an Agent tool response'})
            if paper['cited'] and not paper['read_success']:raise ValueError('Accepted citation without successful read')
        return {'version':72,'kind':'actual_tool_candidates','task_id':task['id'],'as_of':task['at'],
                'source':source,'papers':list(papers.values()),'retrievals':retrievals,
                'provisional':bool(row.get('_in_progress')),'completed_protocol':bool(row.get('completed_protocol')),
                'no_implicit_reads':True,'diagnostic_candidates_injected_into_agent':False,
                'scope':'only candidates returned by actual tools in this run; metadata/explanations are read-only display additions'}
