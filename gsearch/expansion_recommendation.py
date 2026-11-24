"""Original SAR/sklearn adapters over a shared as-of, explicit-version paper catalog."""
import hashlib
import time

import numpy as np
import pandas as pd
import psutil

from .content_recommendation import PARAMS,sklearn_runtime
from .paper_recommendation import PaperRecommender
from .expansion_data import DATA,ROOT,ORIGINAL,read,stamp,tier_records
from .catalog_audit import digest

class ExpansionRecommender:
    def __init__(self,training: pd.DataFrame,records: list[dict],cutoff: object,params: dict|None=None):
        sklearn_runtime()
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.preprocessing import MultiLabelBinarizer,normalize
        self.cutoff=stamp(cutoff)
        self.catalog=sorted(r['doc_id'] for r in records)
        if len(self.catalog)!=len(set(self.catalog)) or not self.catalog:
            raise ValueError('Expected unique nonempty candidate catalog')
        self.by_id={r['doc_id']:r for r in records}
        self.position={d:i for i,d in enumerate(self.catalog)}
        self.available=np.array([stamp(self.by_id[d]['available_at']).timestamp() for d in self.catalog])
        warm=sorted(r['doc_id'] for r in records if r['cohort']=='warm')
        if not warm or any(stamp(self.by_id[d]['available_at'])>=self.cutoff for d in warm):
            raise ValueError('Warm training vocabulary must predate cutoff')
        t=time.perf_counter()
        self.sar=PaperRecommender(training,warm)
        sar_seconds=time.perf_counter()-t
        self.warm_positions=np.array([self.position[d] for d in self.sar.catalog],dtype=np.int32)
        self.popularity=np.array([self.sar.popularity.get(d,0) for d in self.catalog],dtype=np.float64)
        positive=training[(training.rating==1)&training.arxiv_id.isin(warm)]
        histories=positive.groupby('user_id').arxiv_id.agg(lambda x:sorted(set(x))).sort_index()
        self.users=list(histories.index);self.user2row={u:i for i,u in enumerate(self.users)}
        if set(self.users)!=set(self.sar.model.user2index):
            raise ValueError('SAR/content histories differ')
        args=dict(PARAMS if params is None else params);args['ngram_range']=tuple(args['ngram_range'])
        self.vectorizer=TfidfVectorizer(**args)
        text=lambda d:self.by_id[d]['title']+'\n'+self.by_id[d]['abstract']
        initial=[d for d in self.catalog if stamp(self.by_id[d]['available_at'])<self.cutoff]
        t=time.perf_counter()
        self.vectorizer.fit([text(d) for d in initial])
        # Each future document is transformed independently; it never changes vocab/IDF/history.
        self.documents=self.vectorizer.transform([text(d) for d in self.catalog])
        text_seconds=time.perf_counter()-t
        t=time.perf_counter()
        self.history_matrix=MultiLabelBinarizer(classes=self.catalog,sparse_output=True).fit_transform(histories.tolist())
        self.profiles=normalize(self.history_matrix@self.documents,norm='l2',copy=False)
        self.zero_profile_users={self.users[i] for i,n in enumerate(self.profiles.getnnz(axis=1)) if n==0}
        self.fit={'candidates':len(self.catalog),'warm_items_in_sar':len(warm),'initial_text_fit_documents':len(initial),
           'future_transform_only_documents':len(self.catalog)-len(initial),'sar_seconds':sar_seconds,
           'tfidf_fit_and_transform_seconds':text_seconds,'profiles_seconds':time.perf_counter()-t,
           'warm_users':len(self.users),'zero_content_profile_users':len(self.zero_profile_users),
           'vocabulary':len(self.vectorizer.vocabulary_),'sar_matrix_dtype':str(self.sar.model.item_similarity.dtype),
           'sar_matrix_bytes':self.sar.model.item_similarity.nbytes,
           'sparse_bytes':sum(x.data.nbytes+x.indices.nbytes+x.indptr.nbytes for x in (self.documents,self.profiles,self.history_matrix))}

    def sar_scores(self,user: str) -> np.ndarray:
        if user not in self.user2row:
            return self.popularity
        values=self.sar.scores(user,'sar')
        sar=np.zeros(len(self.catalog),dtype=np.float64)
        sar[self.warm_positions]=[values[d] for d in self.sar.catalog]
        return sar

    def content_scores(self,user: str) -> np.ndarray:
        from sklearn.metrics.pairwise import linear_kernel
        if user not in self.user2row or user in self.zero_profile_users:return self.popularity
        return linear_kernel(self.profiles[self.user2row[user]],self.documents).ravel()

    def components(self,user: str) -> tuple[np.ndarray,np.ndarray]:
        return self.sar_scores(user),self.content_scores(user)

    def batch_components(self,users: list[str]) -> tuple[np.ndarray,np.ndarray]:
        """Exact original scorers batched for offline quality replay, not latency measurement."""
        from sklearn.metrics.pairwise import linear_kernel
        cf=np.repeat(self.popularity[None,:],len(users),axis=0)
        text=cf.copy()
        positions=[i for i,u in enumerate(users) if u in self.user2row]
        if positions:
            known=[users[i] for i in positions]
            native=self.sar.model.score(pd.DataFrame({'user_id':known}),remove_seen=False)
            native_order=np.array([self.sar.model.item2index[d] for d in self.sar.catalog])
            cf[positions]=0
            cf[np.ix_(positions,self.warm_positions)]=native[:,native_order]
            text_rows=[i for i in positions if users[i] not in self.zero_profile_users]
            if text_rows:
                text[text_rows]=linear_kernel(self.profiles[[self.user2row[users[i]] for i in text_rows]],self.documents)
        return cf,text

    def eligible(self,user: str,at: object) -> np.ndarray:
        when=stamp(at)
        if when is None or when<self.cutoff:
            raise ValueError('Request must be at/after frozen history cutoff')
        seen=self.sar.seen.get(user,set())
        return np.array([i for i,d in enumerate(self.catalog) if self.available[i]<=when.timestamp() and d not in seen],dtype=np.int32)

    def rank_indices(self,user: str,at: object,method: str,k: int=10,alpha: float=0.5,
                     components: tuple[np.ndarray,np.ndarray]|None=None,
                     eligible_indices: np.ndarray|None=None) -> np.ndarray:
        if method not in ('popular','sar','content','hybrid') or not 0<=alpha<=1 or not 1<=k<=100:
            raise ValueError('Invalid method/alpha/K')
        eligible=self.eligible(user,at) if eligible_indices is None else eligible_indices
        if method=='popular' or user not in self.user2row:
            scores=self.popularity[eligible]
        else:
            if method=='sar' or (method=='hybrid' and alpha==1):
                cf=self.sar_scores(user) if components is None else components[0]
                scores=cf[eligible]
            elif method=='content' or (method=='hybrid' and alpha==0):
                text=self.content_scores(user) if components is None else components[1]
                scores=text[eligible]
            else:
                cf,text=self.components(user) if components is None else components
                cf_order=np.argsort(-cf[eligible],kind='stable');text_order=np.argsort(-text[eligible],kind='stable')
                a,b=np.empty(len(eligible)),np.empty(len(eligible))
                a[cf_order]=np.arange(1,len(eligible)+1);b[text_order]=np.arange(1,len(eligible)+1)
                scores=alpha/(60+a)+(1-alpha)/(60+b)
        if not np.isfinite(scores).all():raise ValueError('Nonfinite scores')
        return eligible[np.argsort(-scores,kind='stable')[:k]]

    def recommend(self,user: str,at: object,method: str='hybrid',k: int=10,alpha: float=.5) -> list[dict]:
        return [{'doc_id':self.catalog[int(i)],'version':self.by_id[self.catalog[int(i)]]['version'],
                 'source_url':self.by_id[self.catalog[int(i)]]['source_url'],'method':method,
                 'cold_user_fallback':user not in self.user2row} for i in self.rank_indices(user,at,method,k,alpha)]

    def read(self,doc: str,at: object) -> dict:
        row=self.by_id.get(doc)
        when=stamp(at)
        if row is None or when is None or when<self.cutoff or stamp(row['available_at'])>when:
            raise ValueError('Paper/version is not available at this request time')
        if row['version']!=1 or row['version_key']!='arxiv:'+doc+'v1':
            raise ValueError('Expected the frozen explicit v1 identity')
        raw=row['provenance']['raw_path']
        from pathlib import Path
        from .expansion_data import CACHE
        if not Path(raw).resolve().is_relative_to((CACHE/'raw').resolve()):
            raise ValueError('Original source response must stay inside the project version cache')
        if digest(Path(raw))!=row['provenance']['raw_sha256']:
            raise ValueError('Original official response hash mismatch')
        from .metadata_fetch import upstream
        from .paper_identity import arxiv_identity
        parsed=upstream()._feed.parse(Path(raw).read_bytes())
        matches=[r for r in parsed.results if arxiv_identity(r.entry_id)==(doc,1)]
        if len(matches)!=1 or matches[0].title!=row['title'] or matches[0].summary!=row['abstract']:
            raise ValueError('Stored text differs from original parsed official v1')
        return {k:row[k] for k in ('doc_id','version','version_key','title','abstract','published_at','available_at','source_url')}|{
            'source_verified':True,'semantic_stance_verified':False,'time_assumption':row['time_assumption']}

def load(n: int=10000) -> ExpansionRecommender:
    receipt=read(ROOT/'corpus-receipt.json')
    if digest(DATA/'documents.json')!=receipt['documents_sha256'] or digest(DATA/f'catalog-{n}.json')!=receipt['catalogs'][str(n)]:
        raise ValueError('Frozen version corpus/catalog changed')
    records=tier_records(read(DATA/'documents.json'),n)
    train=pd.read_csv(ORIGINAL/'train.csv',dtype={'user_id':str,'arxiv_id':str})
    return ExpansionRecommender(train,records,read(ROOT/'admission-plan.json')['cutoff'])

def signature(model: ExpansionRecommender) -> dict:
    def sparse(x: object) -> str:
        h=hashlib.sha256(str(x.shape).encode())
        for a in (x.data,x.indices,x.indptr):h.update(memoryview(a))
        return h.hexdigest()
    import json
    return {'catalog_sha256':hashlib.sha256('\n'.join(model.catalog).encode()).hexdigest(),
       'users_sha256':hashlib.sha256('\n'.join(model.users).encode()).hexdigest(),
       'vocabulary_sha256':hashlib.sha256(json.dumps({k:int(v) for k,v in model.vectorizer.vocabulary_.items()},sort_keys=True).encode()).hexdigest(),
       'idf_sha256':hashlib.sha256(model.vectorizer.idf_.tobytes()).hexdigest(),
       'documents_sha256':sparse(model.documents),'profiles_sha256':sparse(model.profiles),'history_sha256':sparse(model.history_matrix),
       'sar_similarity_sha256':hashlib.sha256(memoryview(model.sar.model.item_similarity)).hexdigest()}
