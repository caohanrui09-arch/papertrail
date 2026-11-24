"""State eligibility adapter; native smolagents owns all execution."""
import json


class ActionState:
    def __init__(self, task: dict):
        self.task=task
        self.required={'search_papers'} if task['intent'] in ('search','empty') else {'recommend_papers'} if task['intent']=='recommend' else {'search_papers','recommend_papers'}
        self.retrieved=set();self.returned={};self.reads={}
        self.charged=0;self.retrieval_charges=0;self.read_charges=0
        self.finished=False;self.snapshots=[];self.events=[];self.wire=[]

    def readable(self) -> list[str]:
        if self.read_charges>=2:return []
        candidates=sorted(set(self.returned)-set(self.reads))
        if self.task['intent']=='mixed' and self.reads:
            if not self.required.issubset(self.retrieved):return []
            origins=set().union(*(self.returned[d] for d in self.reads))
            candidates=[d for d in candidates if self.required.issubset(origins|self.returned[d])]
        return candidates

    def final_count(self) -> int:
        return 0 if not self.returned else 2 if self.task['intent']=='mixed' else 1

    def can_finish(self) -> bool:
        if not self.required.issubset(self.retrieved):return False
        if not self.returned:return True
        if self.task['intent']!='mixed':return bool(self.reads)
        ids=list(self.reads)
        return any(self.required.issubset(self.returned[a]|self.returned[b]) for i,a in enumerate(ids) for b in ids[i+1:])

    def legal(self) -> list[str]:
        if self.charged>=6 or self.finished:return []
        names=[]
        if self.retrieval_charges<2:names+=sorted(self.required-self.retrieved)
        if self.readable():names.append('read_paper')
        if self.can_finish():names.append('final_answer')
        return names

    def observe(self, name: str, result: dict) -> None:
        if name in ('search_papers','recommend_papers'):
            self.retrieved.add(name)
            for paper in result['papers']:self.returned.setdefault(paper['doc_id'],set()).add(name)
        elif name=='read_paper':self.reads[result['doc_id']]=result
        elif name=='finalize':self.finished=True

    def charge(self, calls: list[dict], error: str|None) -> None:
        for call in calls:
            admitted=self.charged<6
            if admitted:
                self.charged+=1
                if call['name'] in ('search_papers','recommend_papers'):self.retrieval_charges+=1
                if call['name']=='read_paper':self.read_charges+=1
            self.events.append({'proposal':call,'charged':admitted,'charged_total':self.charged,'error':error})

    def validate(self, name: str, arguments: dict) -> None:
        public='final_answer' if name=='finalize' else name
        if public not in self.legal():raise ValueError('State action unavailable: '+public)
        if name in ('search_papers','recommend_papers'):
            if type(arguments.get('k')) is not int or not 1<=arguments['k']<=3:
                raise ValueError('Nonnullable integer k in1..3 required; no repair')
            if name=='search_papers' and (not isinstance(arguments.get('query'),str) or not arguments['query'].strip() or len(arguments['query'])>2000):
                raise ValueError('Nonempty query up to2000 characters required')
        elif name=='read_paper':
            if arguments.get('doc_id') not in self.readable():raise ValueError('ID is unavailable/already read')
        elif name=='finalize':
            citations=arguments.get('citations')
            if not isinstance(citations,list) or len(citations)!=self.final_count():
                raise ValueError('Final citation count does not satisfy explicit task')
            seen=set();origins=set()
            for citation in citations:
                if not isinstance(citation,dict) or set(citation)!={'doc_id','quote_index'}:
                    raise ValueError('Exact citation fields required')
                doc,index=citation['doc_id'],citation['quote_index']
                if not isinstance(doc,str) or doc in seen or doc not in self.reads:
                    raise ValueError('Cite distinct already-read IDs')
                if type(index) is not int or not 0<=index<len(self.reads[doc]['quotes']):
                    raise ValueError('Existing integer quote index required')
                seen.add(doc);origins.update(self.returned[doc])
            if citations and not self.required.issubset(origins):raise ValueError('Citations do not cover task retrieval types')

    def refresh(self, agent: object, all_tools: dict) -> None:
        allowed=self.legal();readable=self.readable()
        for name in ('search_papers','recommend_papers'):
            all_tools[name].inputs['k'].update(nullable=False,minimum=1,maximum=3)
        all_tools['read_paper'].inputs['doc_id']['enum']=readable
        count=self.final_count()
        all_tools['final_answer'].inputs['answer']={'type':'object','description':'Final object with model-selected citations to already read papers.',
            'properties':{'citations':{'type':'array','minItems':count,'maxItems':count,'uniqueItems':True,
                'items':{'type':'object','properties':{'doc_id':{'type':'string','enum':sorted(self.reads)},
                    'quote_index':{'type':'integer','minimum':0,'maximum':2}},'required':['doc_id','quote_index'],'additionalProperties':False}}},
            'required':['citations'],'additionalProperties':False}
        agent.tools={name:all_tools[name] for name in allowed}
        state={'legal_tools':allowed,'unread_returned_ids':readable,'read_ids':sorted(self.reads),
            'successful_retrievals':sorted(self.retrieved),'charged_attempts':self.charged,
            'application_attempts_remaining':6-self.charged,'retrieval_attempts_remaining':max(0,2-self.retrieval_charges),
            'read_attempts_remaining':max(0,2-self.read_charges)}
        agent.instructions='Current factual tool state (no relevance labels): '+json.dumps(state)+'. Generate a legal call yourself. k is REQUIRED integer1..3; null is rejected. No automatic calls or final answer.'
        agent.memory.system_prompt.system_prompt=agent.system_prompt
        self.snapshots.append(state)


def parsed_calls(step: object) -> list[dict]:
    calls=getattr(step,'tool_calls',None)
    if calls:return [{'name':call.name,'arguments':call.arguments} for call in calls]
    message=getattr(step,'model_output_message',None)
    calls=getattr(message,'tool_calls',None) if message else None
    return [{'name':call.function.name,'arguments':call.function.arguments} for call in calls or []]
