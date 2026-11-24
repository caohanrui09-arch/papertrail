"""Two frozen profiles, one verified query snapshot and jointly eligible candidate pool.

Only adapts native eligible/content_scores/rank_indices/linear_kernel; no new ranker.
"""
from hashlib import sha256
import json
from pathlib import Path
import time
from typing import Literal
from uuid import UUID,uuid4
from fastapi import HTTPException
from pydantic import BaseModel,ConfigDict,Field


class CompareProfiles(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid')
    version:Literal[76]
    diagnostic_id:str=Field(min_length=36,max_length=36)
    profile_a:Literal['cold','profile-a','profile-b','profile-c']
    profile_b:Literal['cold','profile-a','profile-b','profile-c']


def value_hash(value):return sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
def file_hash(path):return sha256(path.read_bytes()).hexdigest()
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')


def register(app,model,custom,diagnostics,evidence,lock,root:Path):
    import numpy as np
    from sklearn.metrics.pairwise import linear_kernel
    folder=root/'data/stage76-profile-comparisons';folder.mkdir(parents=True,exist_ok=True)
    count=0

    @app.post('/lab/v76/profile-comparison')
    def compare(body:CompareProfiles):
        nonlocal count
        if body.profile_a==body.profile_b:raise HTTPException(422,'请选择两个不同画像')
        try:
            if str(UUID(body.diagnostic_id))!=body.diagnostic_id:raise ValueError('noncanonical')
        except (ValueError,AttributeError):raise HTTPException(422,'诊断ID必须为规范UUID')
        source_path=diagnostics.folder/(body.diagnostic_id+'.json')
        if not source_path.exists():raise HTTPException(404,'先为当前查询运行独立诊断')
        with lock:
            if count>=32:raise HTTPException(429,'本服务双画像对照上限32次；已保留结果')
            source=json.loads(source_path.read_text(encoding='utf8'))
            if source.get('status')!='complete' or source.get('protocol')!=diagnostics.protocol or source.get('as_of')!=custom.at:raise HTTPException(409,'诊断与当前冻结文本、参数或时点不一致')
            if not source.get('query','').strip() or 'pool_ids' not in source:raise HTTPException(422,'双画像对照需要非空查询及原诊断候选池')
            original=source['pool_ids']
            if len(original)>20 or len(set(original))!=len(original) or any(d not in model.position for d in original) or value_hash(original)!=source['pool_ids_sha256']:raise HTTPException(409,'源候选池不一致')
            choices=[custom.profiles[body.profile_a],custom.profiles[body.profile_b]]
            eligible=[set(int(i) for i in model.eligible(p['user_id'],custom.at)) for p in choices]
            ids=sorted(d for d in original if model.position[d] in eligible[0]&eligible[1])
            excluded=[{'doc_id':d,'ineligible_for':[p['id'] for p,valid in zip(choices,eligible) if model.position[d] not in valid]} for d in original if d not in ids]
            histories={p['id']:[model.catalog[int(i)] for i in model.history_matrix[model.user2row[p['user_id']]].indices] if p['user_id'] in model.user2row else [] for p in choices}
            protocol={'version':76,'source_diagnostic_id':body.diagnostic_id,'source_diagnostic_sha256':file_hash(source_path),'query':source['query'],'as_of':custom.at,
                'frozen_algorithm_protocol':diagnostics.protocol,'source_pool_ids':original,'source_pool_ids_sha256':source['pool_ids_sha256'],
                'pool_ids':ids,'pool_ids_sha256':value_hash(ids),'excluded_before_freeze':excluded,
                'filter_rule':'intersection of native eligible(A,at) and eligible(B,at), then freeze; both ranks use exactly this pool',
                'profiles':[{k:p[k] for k in ('id','label','history_size','kind')} for p in choices],
                'history_ids':histories,'history_sha256':{k:value_hash(v) for k,v in histories.items()},
                'ranking':'native rank_indices hybrid; components=(profile_content_scores,query_cosine); alpha=.25; RRF=60; stable catalog ID tie order',
                'cold_rule':'keep shared-pool query order; no popularity injection','quality_evaluation':False,'sent_to_agent':False,
                'source_pool_note':'candidate retrieval originated from the source diagnostic profile; this comparison evaluates within-pool rank changes only'}
            ident=str(uuid4());base=folder/ident;base.mkdir();write(base/'protocol.json',protocol);count+=1
            started=time.perf_counter();result={'id':ident,'version':76,'kind':'independent_shared_pool_profile_comparison','protocol':protocol,'protocol_sha256':file_hash(base/'protocol.json'),'profiles':[],'model_calls':0,'status':'running'}
            try:
                pool=np.array([model.position[d] for d in ids],dtype=np.int32)
                scores=linear_kernel(model.vectorizer.transform([source['query']]),model.documents).ravel()
                baseline=pool[np.argsort(-scores[pool],kind='stable')];query_rank={int(i):n+1 for n,i in enumerate(baseline)}
                for p in choices:
                    t=time.perf_counter();user=p['user_id'];cold=user not in model.user2row or user in model.zero_profile_users
                    profile_scores=None if cold else model.content_scores(user)
                    fallback='无历史或零内容画像，保持同池查询顺序；未注入流行度' if cold else '共同候选池为空' if not len(pool) else None
                    order=baseline if cold or not len(pool) else model.rank_indices(user,custom.at,'hybrid',len(pool),.25,components=(profile_scores,scores),eligible_indices=pool)
                    rows=[]
                    for rank,i in enumerate(order,1):
                        i=int(i);doc=model.catalog[i];anchor=None
                        if not cold:
                            history=model.history_matrix[model.user2row[user]].indices
                            sims=linear_kernel(model.documents[history],model.documents[i]).ravel();j=int(np.argmax(sims));near=model.catalog[int(history[j])]
                            anchor={'doc_id':near,'title':model.by_id[near]['title'],'cosine':float(sims[j])}
                        rows.append({**evidence.metadata(doc),'rank':rank,'query_rank':query_rank[i],'query_cosine':float(scores[i]),'profile_cosine':None if cold else float(profile_scores[i]),'nearest_history_paper':anchor,'fused_score':None})
                    result['profiles'].append({'profile':{k:p[k] for k in ('id','label','history_size','kind')},'cold':cold,'fallback_reason':fallback,'seconds':time.perf_counter()-t,'rows':rows})
                a,b=result['profiles'];ra={p['doc_id']:p['rank'] for p in a['rows']};rb={p['doc_id']:p['rank'] for p in b['rows']}
                result['changes']=[{'doc_id':d,'rank_a':ra[d],'rank_b':rb[d],'delta_b_vs_a':ra[d]-rb[d],'new_in_b_top10':ra[d]>10 and rb[d]<=10,'left_b_top10':ra[d]<=10 and rb[d]>10} for d in ids]
                result['top10_overlap']=len({r['doc_id'] for r in a['rows'][:10]}&{r['doc_id'] for r in b['rows'][:10]})
                result['status']='complete';return result
            except Exception as error:
                result['status']='failed';result['error']=type(error).__name__+': '+str(error);raise HTTPException(500,{'comparison_id':ident,'error':result['error']})
            finally:
                result['seconds']=time.perf_counter()-started;write(base/'result.json',result)
