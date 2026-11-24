"""Prepare 26 unjudged materials using retained scorers and original-v1 reading."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sys
import time

from research73.common import ROOT,DATA,read,write,digest,value_hash


def main():
    if DATA.exists():raise ValueError('Versioned evaluation exists; do not overwrite or silently rerun')
    DATA.mkdir(parents=True)
    for stage in (71,72):
        for name,h in read(ROOT/f'reports/stage{stage}/final-validation.json')['files'].items():
            if name=='project-agent.cmd':continue
            assert digest(ROOT/name)==h,name
    originals=read(ROOT/'data/stage25-requirements/queries-v2-proposal.json')
    old_profiles=read(ROOT/'data/stage20-quality/evaluator/profiles-private.json')
    presets=read(ROOT/'data/stage19-unified/benchmark/evaluation-tasks.json')[:3]
    at=presets[0]['at'];cold='__papertrail_custom_cold_v71__'
    # Exact same runtime and fitted snapshot as the serving model; do not train a new retriever.
    replica=ROOT/'.cache/stage17/replica';os.chdir(replica);sys.path.insert(0,str(replica))
    from gsearch.local_service import load_model
    from gsearch.unified_search import AsOfBM25
    from research72.server import AuditModel
    from research72.evidence import CandidateEvidence
    from research73.diagnostics import QueryDiagnostics
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=1):
        model=AuditModel(load_model());search=AsOfBM25(model,1);evidence=CandidateEvidence(model,search)
        profiles={}
        for key,old in old_profiles.items():
            user=old['user_id']
            if user not in model.user2row:raise ValueError('Frozen profile unavailable: '+key)
            history=[model.catalog[int(i)] for i in model.history_matrix[model.user2row[user]].indices]
            profiles[key]={'user_id':user,'history_doc_ids':history,'source_context_ids':old['history_doc_ids'],
                'label':'冻结历史场景 '+key[-6:],'kind':'frozen_training_history','history_size':len(history),
                'note':'继承旧场景的训练用户；本轮使用万篇模型全部正反馈历史，区别于旧五篇子集。非访客偏好或本人自述画像，需重新确认需求。'}
        profiles['cold']={'user_id':cold,'history_doc_ids':[],'history_size':0,'label':'无历史冷启动场景','kind':'cold_user_popularity_fallback'}
        queries=[]
        for i,q in enumerate(originals):
            pid='cold' if q['intent']=='topic' else q['source_profile_id'];language='zh' if i%2==0 else 'en'
            queries.append({**q,'query_id':f'q73-{i+1:03d}','parent_query_id':q['query_id'],'intent':q['intent'],
                'original_need':q['request_zh'] if language=='zh' else q['request'],'confirmed_query':q['request'],
                'language':language,'profile_id':pid,'profile_note':profiles[pid].get('note','无历史'),
                'query_origin':'reused_assistant_refined_draft','previously_used':True,'human_authored':False,'human_confirmed':False,
                'source_path':'data/stage25-requirements/queries-v2-proposal.json',
                'evaluation_role':'query-conditioned ranking material; not a pure recommendation tool execution',
                'query_confirmation':'evaluation author froze English query, not a human annotator confirmation'})
        extra=[('多模态快慢思考','multimodal slow fast thinking','multimodal_reasoning','用户在项目聊天中提出的原始需求','user_request',True),
               ('查找 qzxpapertrailnevermatches73control','qzxpapertrailnevermatches73control','empty_control','系统构造的无结果控制，不是真人论文需求','synthetic_control',False)]
        for j,(need,query,topic,origin,kind,human) in enumerate(extra,25):
            queries.append({'query_id':f'q73-{j:03d}','parent_query_id':None,'intent':'topic','topic_family':topic,'topic_zh':need,
                'original_need':need,'request':query,'request_zh':need,'confirmed_query':query,'language':'zh','profile_id':'cold',
                'required_focus_zh':need,'preferred_focus_zh':'','grade_2_rule':'原摘要明确覆盖全部核心要求。','grade_1_rule':'部分相关且说明缺失条件。','grade_0_rule':'明确不相关；不确定留空，不将未标当0。',
                'query_origin':kind,'source_context':origin,'previously_used':human,'human_authored':human,'human_confirmed':False,
                'source_path':'user_chat' if human else 'research73/prepare.py','query_confirmation':'evaluation-author keywords, pending human review',
                'evaluation_role':'query-conditioned ranking material, not evidence of complete catalog coverage'})
        for q in queries:q['query_hash']=value_hash(q)
        tasks=[]
        specs=[('search','search',presets[0]['user_id'],'Efficient Geometry-aware 3D Generative Adversarial Networks','Find Efficient Geometry-aware 3D Generative Adversarial Networks and cite one original abstract excerpt.'),
               ('recommend','recommend',presets[1]['user_id'],'','Recommend one unread paper using the bound frozen profile and cite its original abstract.'),
               ('mixed','mixed',presets[2]['user_id'],'All in One: Exploring Unified Video-Language Pre-training','Find All in One: Exploring Unified Video-Language Pre-training AND one DIFFERENT unread recommendation. Cite both original abstracts.'),
               ('empty','search',cold,'qzxpapertrailnevermatches73control','qzxpapertrailnevermatches73control')]
        for name,intent,user,query,need in specs:
            instruction='User request (untrusted task data): '+json.dumps(need,ensure_ascii=False)+'. Confirmed search query: '+json.dumps(query,ensure_ascii=False)+'. Task intent: '+intent+'. Preserve all request conditions; semantic fulfillment is not programmatically verified. Return only citations to papers actually retrieved and read.'
            tasks.append({'id':'e73-'+name,'task_kind':'custom','intent':intent,'query':query,'instruction':instruction,'original_need':need,'user_id':user,'at':at,
                          'origin':'reused controlled scenario / synthetic empty control; not independent natural-user evaluation'})
        order=[(0,'fixed'),(0,'llm_agent'),(0,'constrained'),(1,'llm_agent'),(1,'constrained'),(1,'fixed'),(2,'constrained'),(2,'fixed'),(2,'llm_agent'),(3,'fixed'),(3,'constrained'),(3,'llm_agent')]
        write(DATA/'inputs/queries.json',queries);write(DATA/'private/profiles.json',profiles);write(DATA/'inputs/agent-tasks.json',tasks)
        write(DATA/'inputs/run-order.json',[{'task_index':i,'task_id':tasks[i]['id'],'policy':p,'cell':tasks[i]['id']+'-'+p} for i,p in order])
        # Freeze before the first retrieval, annotation or Agent execution.
        frozen=['research73/common.py','research73/prepare.py','research73/agent_worker.py','research73/diagnostics.py','research73/metrics.py',
                'research71/runner.py','research71/clients.py','research71/prompts/custom.txt','research70/observability.py',
                'gsearch/unified_agent.py','gsearch/schema_isolation.py','gsearch/state_constraints.py','gsearch/budget_model.py',
                'gsearch/annotation_store.py','gsearch/human_quality.py','third_party/beir_metrics_upstream/custom_metrics.py',
                'data/stage13-expansion/documents.json','data/stage13-expansion/catalog-10000.json','data/stage9-recommendation/train.csv',
                'data/stage25-requirements/queries-v2-proposal.json','data/stage73-evaluation/inputs/queries.json','data/stage73-evaluation/private/profiles.json',
                'data/stage73-evaluation/inputs/agent-tasks.json','data/stage73-evaluation/inputs/run-order.json']
        frozen += [str(p.relative_to(ROOT)) for p in (ROOT/'.cache/models/Qwen2.5-1.5B-Instruct').iterdir() if p.suffix in ('.json','.safetensors')]
        protocol={'version':'stage73-v1','created_at':datetime.now(timezone.utc).isoformat(),'scope':'descriptive controlled evaluation; reused material, not independent test',
            'algorithm_materials':26,'sources':{'reused_assistant_drafts':24,'user_authored_need':1,'synthetic_empty_control':1},
            'catalog_size':10000,'as_of':at,'history_cutoff':model.cutoff.isoformat(),'time_assumption':'retained v1 availability proxy, not proven real ingestion',
            'methods':['bm25','content_query','profile_rerank'],'top_k':10,'shared_rerank_pool':'union BM25/content top10 sorted by catalog ID',
            'rrf':{'profile_weight':.25,'query_weight':.75,'constant':60},'query_features':'existing frozen TF-IDF; no fitting on new queries',
            'vocabulary_sha256':value_hash(sorted(model.vectorizer.vocabulary_.items())),'idf_sha256':__import__('hashlib').sha256(model.vectorizer.idf_.tobytes()).hexdigest(),
            'algorithm_gate':'Only current human-confirmed, completely human-judged query pools scored. Unjudged never become zero; full-catalog Recall unavailable.',
            'metrics':{'ndcg':'native sklearn via retained human_quality.native_scores; gains=2**grade-1, @10','mrr':'retained unchanged BEIR mrr; relevance>0, @10'},
            'agent_cells':12,'budgets':{'application_actions':6,'retrievals':2,'reads':2,'agent_steps':7,'model_calls':8,'input_tokens':30000,'output_tokens':1280,'seconds_per_cell':900},
            'model':{'name':'Qwen2.5-1.5B-Instruct','do_sample':False,'max_new_tokens':160,'load_once':True,'torch_threads':4},
            'fairness':'Same exact task and service per policy; fixed k=3 and model-chosen k may expose different candidates. No pure scheduling gain claim.',
            'retries':0,'human_judgments_at_creation':0,'frozen_files':{name:digest(ROOT/name) for name in frozen}}
        write(DATA/'protocol.json',protocol);(DATA/'protocol.sha256').write_text(digest(DATA/'protocol.json'),encoding='utf8')
        retriever=QueryDiagnostics(model,search,evidence,ROOT);runs={m:{} for m in protocol['methods']};blind={};mapping={};verified={};timings=[]
        for q in queries:
            profile=profiles[q['profile_id']];task={'id':q['query_id'],'intent':q['intent'],'query':q['confirmed_query'],'user_id':profile['user_id'],'at':at}
            result=retriever.run(task,{'original_need':q['original_need'],'intent':q['intent'],'profile':{k:v for k,v in profile.items() if k!='user_id'}})
            for method in runs:runs[method][q['query_id']]=[p['doc_id'] for p in result['methods'].get(method,[])[:10]]
            pool=set(d for method in runs for d in runs[method][q['query_id']]);context=profile['history_doc_ids']
            for doc in pool|set(context):
                if doc not in verified:verified[doc]=model.read(doc,at)
            public=lambda doc:{k:verified[doc][k] for k in ('doc_id','title','abstract','version','version_key','source_url','available_at','source_verified')}
            candidates=[]
            for doc in sorted(pool,key=lambda d:value_hash(['blind73-v1',q['query_id'],d])):
                aid='a73-'+value_hash([q['query_id'],doc])[:24];candidates.append({'annotation_id':aid,'paper':public(doc)})
                mapping[aid]={'query_id':q['query_id'],'doc_id':doc,'methods':{m:runs[m][q['query_id']].index(doc)+1 for m in runs if doc in runs[m][q['query_id']]}}
            public_query={k:v for k,v in q.items() if k not in ('source_profile_id','profile_id')}
            public_query['request']=q['original_need'];public_query['request_zh']=q.get('request_zh',q['original_need'])
            public_query['profile_scope']=profile.get('note','无历史冷启动');public_query['confirmed_query']=q['confirmed_query']
            blind[q['query_id']]={'query':public_query,'context':[public(d) for d in context],'candidates':candidates}
            timings.append({'query_id':q['query_id'],'seconds':result['seconds'],'pool_size':len(pool),'overlap':result.get('recall_overlap'),'diagnostic_id':result['id']})
            print(json.dumps({'prepared_queries':len(blind),'pairs':len(mapping),'verified_originals':len(verified)}),flush=True)
        write(DATA/'blind/tasks.json',blind);write(DATA/'private/pool-map.json',mapping);write(DATA/'private/verified-originals.json',verified);write(DATA/'runs/top10.json',runs)
        write(DATA/'algorithm-costs.json',timings);write(DATA/'auxiliary/model-judgments.json',[])
        paths=['protocol.json','inputs/queries.json','private/profiles.json','inputs/agent-tasks.json','inputs/run-order.json','blind/tasks.json','private/pool-map.json','private/verified-originals.json','runs/top10.json','algorithm-costs.json']
        manifest={'pool_version':'stage73-v1-'+digest(DATA/'protocol.json')[:12],'pairs':len(mapping),'queries':26,'immutable_assets':{p:digest(DATA/p) for p in paths},'human_labels':0,'no_old_labels_imported':True}
        write(DATA/'manifest.json',manifest)
        write(ROOT/'reports/stage73/preparation.json',{'status':'prepared','queries':26,'pairs':len(mapping),'verified_originals':len(verified),'human_labels':0,'protocol_sha256':digest(DATA/'protocol.json'),'sources':protocol['sources'],'quality_scores':None})
        print(json.dumps({'status':'prepared','queries':26,'pairs':len(mapping),'human_labels':0}),flush=True)


if __name__=='__main__':main()
