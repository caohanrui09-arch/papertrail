"""Frozen-query diagnostic retrieval and native RRF on a shared pool; not Agent tools."""
import hashlib
import json
from pathlib import Path
import time
import uuid
from typing import Any

import numpy as np


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


class QueryDiagnostics:
    def __init__(self,model: Any,search: Any,evidence: Any,root: Path):
        self.model=model;self.search=search;self.evidence=evidence;self.folder=root/'data/stage74-diagnostics';self.folder.mkdir(parents=True,exist_ok=True)
        self.terms=model.vectorizer.get_feature_names_out()
        self.protocol={'version':72,'top_k':10,'pool':'union of BM25 top10 and positive query-cosine top10; sorted by catalog ID',
            'alpha_profile':.25,'rrf_constant':60,'tie_rule':'native stable sort; shared pool in catalog ID order',
            'content':'existing fitted sklearn TfidfVectorizer.transform + linear_kernel; positive cosine only',
            'vocabulary_sha256':digest(sorted(model.vectorizer.vocabulary_.items())),
            'idf_sha256':hashlib.sha256(model.vectorizer.idf_.tobytes()).hexdigest(),
            'vectorizer_params':{k:str(v) for k,v in model.vectorizer.get_params().items()},
            'documents_sha256':hashlib.sha256((root/'data/stage13-expansion/documents.json').read_bytes()).hexdigest(),
            'catalog_sha256':digest(model.catalog),'history_cutoff':model.cutoff.isoformat(),
            'agent_default_unchanged':True,'quality_labels':0,'scope':'diagnostic only; no SFT, tuning or default replacement'}
        path=self.folder/'protocol.json'
        if path.exists() and json.loads(path.read_text())!=self.protocol:raise ValueError('Diagnostic protocol changed; version it instead')
        if not path.exists():path.write_text(json.dumps(self.protocol,ensure_ascii=False,indent=2),encoding='utf8')

    def run(self,task: dict,context: dict) -> dict:
        from sklearn.metrics.pairwise import linear_kernel
        started=time.perf_counter();ident=str(uuid.uuid4());model=self.model
        eligible=model.eligible(task['user_id'],task['at']);eligible_ids=[model.catalog[int(i)] for i in eligible]
        record={'id':ident,'kind':'independent_algorithm_diagnostic','task_id':task['id'],'as_of':task['at'],'query':task['query'],
            'context':context,'protocol':self.protocol,'eligible_count':len(eligible),'eligible_ids_sha256':digest(eligible_ids),
            'methods':{},'method_info':{},'quality_evaluation':False,'agent_tools_changed':False}
        try:
            if not task['query'].strip():
                record['note']='推荐任务没有检索词，不运行搜索对照；实际推荐候选见本次工具返回。'
                return self.finish(record,started)
            t=time.perf_counter();bm=self.search.search(task['user_id'],task['at'],task['query'],10)
            bm_seconds=time.perf_counter()-t
            t=time.perf_counter();query=model.vectorizer.transform([task['query']]);scores=linear_kernel(query,model.documents).ravel()
            positive=eligible[scores[eligible]>0];order=positive[np.argsort(-scores[positive],kind='stable')[:10]]
            content_seconds=time.perf_counter()-t
            def item(i: int,method: str,score: float|None) -> dict:
                doc=model.catalog[int(i)];weighted=query.multiply(model.documents[int(i)]).tocoo()
                indices=np.argsort(-weighted.data,kind='stable')[:8];terms=self.terms
                return {**self.evidence.metadata(doc),'method':method,'score':score,'query_cosine':float(scores[int(i)]),
                        'query_term_products':[{'term':str(terms[weighted.col[j]]),'product':float(weighted.data[j])} for j in indices],
                        'profile_cosine':None,'nearest_history_paper':None}
            bm_rows=[]
            for hit in bm['papers']:
                row=item(model.position[hit['doc_id']],'bm25',hit['score'])
                row['fts_evidence']=self.evidence.search_details(task['at'],task['query'],hit['doc_id']);bm_rows.append(row)
            content_rows=[item(int(i),'content_query',float(scores[int(i)])) for i in order]
            record['methods'].update(bm25=bm_rows,content_query=content_rows)
            record['method_info'].update(bm25={'kind':'retrieval','seconds':bm_seconds,'note':'原生 SQLite FTS5 BM25；正向展示分数越大越靠前'},content_query={'kind':'retrieval','seconds':content_seconds,'note':'冻结词表上的查询—文档余弦，不是语义向量模型'})
            a={r['doc_id'] for r in bm_rows};b={r['doc_id'] for r in content_rows};pool_ids=sorted(a|b)
            pool=np.array([model.position[d] for d in pool_ids],dtype=np.int32)
            record.update({'recall_overlap':{'bm25_count':len(a),'content_count':len(b),'intersection':len(a&b),'union':len(a|b),'jaccard':len(a&b)/len(a|b) if a|b else None},
                           'pool_ids':pool_ids,'pool_ids_sha256':digest(pool_ids),'query_nonzero_features':query.nnz})
            baseline=pool[np.argsort(-scores[pool],kind='stable')]
            cold=task['user_id'] not in model.user2row or task['user_id'] in model.zero_profile_users
            t=time.perf_counter();profile_scores=None
            if cold or not len(pool):reranked=baseline;fallback='无历史或零内容画像；保持共享池查询排序，不注入流行度' if cold else '共享候选池为空'
            else:
                profile_scores=model.content_scores(task['user_id'])
                reranked=model.rank_indices(task['user_id'],task['at'],'hybrid',len(pool),.25,components=(profile_scores,scores),eligible_indices=pool)
                fallback=None
            rerank_seconds=time.perf_counter()-t
            def pool_item(i: int,method: str) -> dict:
                row=item(i,method,float(scores[i]) if method=='pool_content' else None)
                if profile_scores is not None:
                    row['profile_cosine']=float(profile_scores[i]);history=model.history_matrix[model.user2row[task['user_id']]].indices
                    sims=linear_kernel(model.documents[history],model.documents[i]).ravel();j=int(np.argmax(sims));doc=model.catalog[int(history[j])]
                    row['nearest_history_paper']={'doc_id':doc,'title':model.by_id[doc]['title'],'cosine':float(sims[j])}
                row['fallback_reason']=fallback;return row
            record['methods'].update(pool_content=[pool_item(int(i),'pool_content') for i in baseline],profile_rerank=[pool_item(int(i),'profile_rerank') for i in reranked])
            record['method_info'].update(pool_content={'kind':'shared_pool_baseline','pool_ids_sha256':digest(pool_ids),'note':'共享池按查询余弦排序；完整池最多20篇'},profile_rerank={'kind':'shared_pool_rerank','pool_ids_sha256':digest(pool_ids),'seconds':rerank_seconds,'fallback_reason':fallback,'note':'原生 rank_indices hybrid，画像权重0.25、查询权重0.75、RRF=60；原函数只返回顺序，融合标量留空'})
            record['cold_profile']=cold
            return self.finish(record,started)
        except Exception as error:
            record['status']='failed';record['error']=type(error).__name__+': '+str(error);self.finish(record,started);raise

    def finish(self,record: dict,started: float) -> dict:
        record.setdefault('status','complete');record['seconds']=time.perf_counter()-started
        (self.folder/(record['id']+'.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
        return record
