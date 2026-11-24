"""As-of recommendation -> exact-source-v1 abstract reading, CLI and genuine tools."""
import argparse
import json
from pathlib import Path

from .expansion_recommendation import load
from .expansion_data import ROOT,save,read
from .catalog_audit import stamp

class ExpansionSession:
    def __init__(self,model: object,user_id: str,at: str,method: str='hybrid',alpha: float=.5,max_calls: int=4):
        if stamp(at) is None or stamp(at)<model.cutoff:raise ValueError('Invalid request timestamp')
        self.model=model;self.user_id=user_id;self.at=at;self.method=method;self.alpha=alpha
        self.max_calls=max_calls;self.trace=[];self.returned=set()

    def recommend(self,k: int=10) -> dict:
        if len(self.trace)>=self.max_calls:raise ValueError('Tool budget exhausted')
        hits=self.model.recommend(self.user_id,self.at,self.method,k,self.alpha)
        self.returned.update(r['doc_id'] for r in hits)
        result={'user_id':self.user_id,'as_of':self.at,'papers':hits,'history_cutoff':self.model.cutoff.isoformat(),
                'temporal_assumption':'v1 submission-day end plus24h, not proven historical ingestion',
                'cold_user_fallback':self.user_id not in self.model.user2row}
        self.trace.append({'tool':'recommend_papers','result':result});return result

    def read(self,doc_id: str) -> dict:
        if len(self.trace)>=self.max_calls:raise ValueError('Tool budget exhausted')
        if doc_id not in self.returned:raise ValueError('Paper must first be returned by this as-of recommendation')
        result=self.model.read(doc_id,self.at)
        self.trace.append({'tool':'read_paper','result':result});return result

def make_tools(session: ExpansionSession) -> list:
    from smolagents import tool
    @tool
    def recommend_papers(k: int=10) -> dict:
        """Recommend unread papers from the shared catalog available at the fixed request time.

        Args:
            k: Number of papers, between1 and100.
        """
        return session.recommend(k)
    @tool
    def read_paper(doc_id: str) -> dict:
        """Read the exact original arXiv v1 abstract of a paper already recommended in this session.

        Args:
            doc_id: Base arXiv ID returned by recommend_papers.
        """
        return session.read(doc_id)
    return [recommend_papers,read_paper]

def main() -> None:
    p=argparse.ArgumentParser();p.add_argument('--user',required=True);p.add_argument('--at',required=True)
    p.add_argument('--tier',type=int,choices=(1000,5000,10000),default=10000)
    p.add_argument('--method',choices=('popular','sar','content','hybrid'),default='hybrid');p.add_argument('--k',type=int,default=3)
    p.add_argument('--read-top1',action='store_true');p.add_argument('--output',type=Path)
    a=p.parse_args()
    lock=read(ROOT/'locked-before-dev.json');alpha=lock['tiers'][str(a.tier)]['alpha']
    model=load(a.tier);session=ExpansionSession(model,a.user,a.at,a.method,alpha)
    tools={t.name:t for t in make_tools(session)}
    result=tools['recommend_papers'](k=a.k)
    original=tools['read_paper'](doc_id=result['papers'][0]['doc_id']) if a.read_top1 and result['papers'] else None
    out={'recommendation':result,'original_version_abstract':original,'trace':session.trace}
    if a.output:
        if not a.output.resolve().is_relative_to(Path('data').resolve()):raise ValueError('Per-user outputs must stay in ignored local data/')
        save(a.output,out)
        print(json.dumps({'output':str(a.output),'source_verified':original['source_verified'] if original else None}),flush=True)
    else:print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
