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

    def _budget_line(self) -> str:
        return (f'attempts={self.charged}/6 retrieval={self.retrieval_charges}/2 read={self.read_charges}/2 '
                f'returned={len(self.returned)} read_ids={sorted(self.reads)} required={sorted(self.required)}')

    def _reject(self, code: str, action: str, detail: str) -> None:
        # Same decision, clearer reason: the model and the auditor both read this.
        raise ValueError(f'reason={code} action={action} {detail} | {self._budget_line()}')

    def _unavailable_code(self, name: str) -> tuple[str, str]:
        if self.finished:return ('already_finalized','the task is already finalized')
        if self.charged>=6:return ('budget_exhausted','all 6 application attempts are used; the run cannot continue')
        if name in ('search_papers','recommend_papers'):
            if name in self.retrieved:return (f'{name}_already_used',f'{name} already ran in this task; a retrieval cannot be repeated')
            if self.retrieval_charges>=2:return ('retrieval_budget_exhausted','both retrieval attempts are used')
            if name not in self.required:return ('retrieval_not_required',f'{name} is not required for intent={self.task["intent"]}')
        if name=='read_paper':
            if self.read_charges>=2:return ('read_budget_exhausted','both read attempts are used')
            if not self.returned:return ('read_requires_returned_paper','no paper has been returned yet; run the required retrieval first')
            if self.task['intent']=='mixed' and self.reads and not self.required.issubset(self.retrieved):
                return ('read_requires_other_retrieval','the mixed task still needs the other retrieval before a second read')
            return ('read_not_in_readable','no unread returned paper satisfies the mixed branch rule')
        if name in ('finalize','final_answer'):
            missing=sorted(self.required-self.retrieved)
            if missing:return ('final_requires_retrieval',f'final_answer needs these retrievals first: {missing}')
            if self.returned and not self.reads:return ('final_requires_read','papers were returned but none was read')
            if self.task['intent']=='mixed':return ('final_requires_two_branch_reads','a mixed task needs two reads, one from each retrieval type')
        return ('action_unavailable','not a legal action in the current state')

    def _read_code(self, doc: object) -> str:
        if self.read_charges>=2:return 'read_budget_exhausted'
        if isinstance(doc,str) and doc in self.reads:return 'read_already_read'
        if not isinstance(doc,str) or doc not in self.returned:return 'read_never_returned'
        if self.task['intent']=='mixed' and self.reads:
            if not self.required.issubset(self.retrieved):return 'read_requires_other_retrieval'
            origins=set().union(*(self.returned[d] for d in self.reads))
            if not self.required.issubset(origins|self.returned[doc]):return 'read_wrong_branch'
        return 'read_not_in_readable'

    def _read_detail(self, doc: object) -> str:
        if self.read_charges>=2:return f'{doc!r} rejected because both read attempts are used'
        if isinstance(doc,str) and doc in self.reads:return f'{doc} was already read in this task'
        if not isinstance(doc,str) or doc not in self.returned:
            return f'{doc!r} was never returned by a retrieval in this task; only IDs from actual tool responses are readable'
        if self.task['intent']=='mixed' and self.reads:
            origins=sorted(self.returned[doc])
            other=sorted(self.required-set().union(*(self.returned[d] for d in self.reads)))
            return f'{doc} came from {origins}, but the mixed task still needs a paper from {other}; readable ids now: {self.readable()}'
        return f'{doc} is not in the current readable set; readable ids now: {self.readable()}'

    def validate(self, name: str, arguments: dict) -> None:
        public='final_answer' if name=='finalize' else name
        if public not in self.legal():
            if name=='read_paper':
                # Same rejection, but name the concrete ID condition instead of a generic gate.
                doc=arguments.get('doc_id')
                self._reject(self._read_code(doc),'read_paper',self._read_detail(doc))
            code,detail=self._unavailable_code(name)
            self._reject(code,public,detail)
        if name in ('search_papers','recommend_papers'):
            if type(arguments.get('k')) is not int or not 1<=arguments['k']<=3:
                self._reject('invalid_k',public,f'k must be an integer 1..3, got {arguments.get("k")!r}; no automatic repair')
            if name=='search_papers' and (not isinstance(arguments.get('query'),str) or not arguments['query'].strip() or len(arguments['query'])>2000):
                query=arguments.get('query')
                self._reject('invalid_query',public,f'query must be a nonempty string up to 2000 characters, got length={len(query) if isinstance(query,str) else type(query).__name__}')
        elif name=='read_paper':
            doc=arguments.get('doc_id')
            if doc not in self.readable():
                self._reject(self._read_code(doc),'read_paper',self._read_detail(doc))
        elif name=='finalize':
            citations=arguments.get('citations')
            expected=self.final_count()
            if not isinstance(citations,list) or len(citations)!=expected:
                got=len(citations) if isinstance(citations,list) else type(citations).__name__
                self._reject('final_citation_count','final_answer',f'expected exactly {expected} citation(s) for intent={self.task["intent"]} with returned={len(self.returned)}; got {got}')
            seen=set();origins=set()
            for citation in citations:
                if not isinstance(citation,dict) or set(citation)!={'doc_id','quote_index'}:
                    fields=sorted(citation) if isinstance(citation,dict) else type(citation).__name__
                    self._reject('final_citation_fields','final_answer',f'each citation needs exactly doc_id and quote_index; got {fields}')
                doc,index=citation['doc_id'],citation['quote_index']
                if not isinstance(doc,str) or doc in seen or doc not in self.reads:
                    self._reject('final_citation_unusable','final_answer',f'cite distinct papers that were actually read; doc_id={doc!r} already_cited={doc in seen} was_read={isinstance(doc,str) and doc in self.reads}')
                if type(index) is not int or not 0<=index<len(self.reads[doc]['quotes']):
                    self._reject('final_quote_index','final_answer',f'quote_index for {doc} must be an integer 0..{len(self.reads[doc]["quotes"])-1}')
                seen.add(doc);origins.update(self.returned[doc])
            if citations and not self.required.issubset(origins):
                self._reject('final_citation_coverage','final_answer',f'citations must cover retrieval types {sorted(self.required-origins)}; covered={sorted(origins)}')

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
        if allowed:
            suffix='Generate a legal call yourself. k is REQUIRED integer1..3; null is rejected. No automatic calls or final answer.'
        elif self.finished:
            suffix='The task is already finalized; no further action is possible.'
        else:
            suffix=f'TERMINAL: no legal action remains (attempts used {self.charged}/6). The run will end; do not invent citations or a final answer.'
        agent.instructions='Current factual tool state (no relevance labels): '+json.dumps(state)+'. '+suffix
        agent.memory.system_prompt.system_prompt=agent.system_prompt
        self.snapshots.append(state)


def parsed_calls(step: object) -> list[dict]:
    calls=getattr(step,'tool_calls',None)
    if calls:return [{'name':call.name,'arguments':call.arguments} for call in calls]
    message=getattr(step,'model_output_message',None)
    calls=getattr(message,'tool_calls',None) if message else None
    return [{'name':call.function.name,'arguments':call.function.arguments} for call in calls or []]