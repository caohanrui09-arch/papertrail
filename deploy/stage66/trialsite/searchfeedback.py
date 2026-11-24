"""Evidence adapter over the existing FTS5 index / frozen TF-IDF analyzer."""
import re
from typing import Literal
from fastapi import FastAPI,Query
from .catalog import Catalog
from .catalogfilters import Scope,scoped_ids,filter_info
from .querybridge import plan_query

LABELS={'generative':'生成式检索','cold':'推荐冷启动','bias':'曝光与评价'}
STOP={'a','an','the','is','are','of','to','in','and','or','that','with','for','by'}

class SearchFeedback:
    def __init__(self,catalog:Catalog)->None:
        self.catalog=catalog
        self.analyzer=catalog.vectorizer.build_analyzer()
        self.suggestions={}
        for method in ('bm25','tfidf'):
            self.suggestions[method]=[{'topic':topic,'label':LABELS[topic],'query':config['core']}
                for topic,config in catalog.topics.items()
                if catalog.search(topic,config['core'],method,'none')['papers']]

        if hasattr(catalog,'supplement'):
            for method in ('bm25','tfidf'):
                self.suggestions[method].append({'topic':'generative','label':catalog.supplement['label'],'query':catalog.supplement['query'],'catalog_scope':'multimodal'})

    def explain(self,result:dict,method:str,allowed_ids:set[str]|None=None)->dict:
        c=self.catalog;query=result['query'];eligible=set(c.catalog)-c.model.sar.seen['paired']
        if allowed_ids is not None:eligible &= allowed_ids
        matches={d:[] for d in result['candidate_ids_before_rerank']}
        in_catalog=[];missing=[];ignored=[]
        if method=='bm25':
            # Same bounded word extraction as the existing search adapter, only for evidence.
            all_terms=list(dict.fromkeys(re.findall(r'\w+',query.casefold())))[:128]
            terms=[t for t in all_terms if t not in STOP];ignored=[t for t in all_terms if t in STOP]
            with c.bm25.lock:
                db,_=c.bm25._snapshot(c.at)
                # Actual FTS5 matching uses the same porter unicode61 tokenizer, not a substring heuristic.
                for term in terms:
                    expression='"'+term+'"'
                    ids={row[0] for row in db.execute('SELECT doc_id FROM docs WHERE docs MATCH ?',(expression,))}
                    (in_catalog if (ids & eligible if allowed_ids is not None else ids) else missing).append(term)
                    for field,column in [('title','title'),('abstract','body')]:
                        hit={row[0] for row in db.execute('SELECT doc_id FROM docs WHERE docs MATCH ?',(column+' : '+expression,))}
                        for doc in matches:
                            if doc in hit:
                                found=next((x for x in matches[doc] if x['term']==term),None)
                                if found:found['fields'].append(field)
                                else:matches[doc].append({'term':term,'fields':[field]})
            truncated=len(list(dict.fromkeys(re.findall(r'\w+',query.casefold()))))>128
            kind='FTS5 词项匹配（含英文词干归一化）'
        else:
            all_terms=list(dict.fromkeys(self.analyzer(query)));terms=all_terms[:128]
            vocabulary=c.vectorizer.vocabulary_
            for term in terms:
                if term not in vocabulary or (allowed_ids is not None and not any(c.documents[c.position[d],vocabulary[term]]>0 for d in eligible)):missing.append(term);continue
                in_catalog.append(term);index=vocabulary[term]
                for doc in matches:
                    if c.documents[c.position[doc],index]<=0:continue
                    fields=[]
                    row=c.by_id[doc]
                    if term in self.analyzer(row['title']):fields.append('title')
                    if term in self.analyzer(row['abstract']):fields.append('abstract')
                    matches[doc].append({'term':term,'fields':fields or ['boundary']})
            truncated=len(all_terms)>128
            kind='TF-IDF 实际非零词项（含配置中的词组）'
        rows=[{**p,'search_match':{'query':query,'method':method,'kind':kind,'terms':matches[p['doc_id']],
              'partial':truncated}} for p in result['papers']]
        extra=[c.supplement['label']] if hasattr(c,'supplement') else []
        return {**result,'papers':rows,'feedback':{'catalog':len(c.catalog),'eligible':len(eligible),
            'excluded':len(c.catalog)-len(eligible),'topics':list(LABELS.values())+extra,'as_of':c.at,
            'query':query,'method':method,'kind':kind,'indexed_terms':in_catalog,'unmatched_terms':missing,
            'ignored_terms':ignored,'terms_truncated':truncated,'returned':len(rows),
            'suggestions':self.suggestions[method],
            'scope':('当前网站包含'+str(len(c.core.catalog))+'篇历史核心与'+str(len(c.supplement_ids))+'篇新增专题；混合目录不用于历史评价。' if hasattr(c,'core') else '仅搜索当前专题目录的标题和原v1摘要；专题切换提供起始查询，搜索覆盖整个可用目录。'),
            'notice':'未返回结果仅说明本次查询在当前范围没有可返回的词项匹配，不代表论文不存在。' if not rows else '词项匹配不等于语义相关性或论文质量；高亮仍仅表示字面匹配。'}}

def install_searchfeedback(app:FastAPI)->None:
    adapter=SearchFeedback(app.state.catalog)
    core_adapter=SearchFeedback(app.state.catalog.core)
    # Preserve the old response exactly by default; enhanced requests use the same route and rate budget.
    app.router.routes[:]=[r for r in app.router.routes if getattr(r,'path',None)!='/api/search']
    @app.get('/api/search')
    def search(topic:Literal['generative','cold','bias'],q:str=Query(min_length=1,max_length=1000),
               method:Literal['bm25','tfidf']='bm25',context:Literal['none','same','cross']='none',explain:bool=False,need:str=Query(default='',max_length=1000),plan_reviewed:bool=False,catalog_scope:Scope='core',year:int|None=Query(default=None,ge=1900,le=2100)):
        from fastapi import HTTPException
        if not q.strip():raise HTTPException(422,'请输入查询')
        bridge=plan_query(need,q,plan_reviewed) if need.strip() else None
        if bridge and bridge['review_required'] and not plan_reviewed:raise HTTPException(422,'请检查未识别或排除表达，并确认检索词后再搜索')
        selected=app.state.catalog.core if catalog_scope=='core' else app.state.catalog
        selected_adapter=core_adapter if catalog_scope=='core' else adapter
        filtered=catalog_scope not in ('all','core') or year is not None
        allowed=scoped_ids(app.state.catalog,catalog_scope,year) if filtered else None
        result=selected.search(topic,q,method,context,allowed_ids=allowed)
        result=selected_adapter.explain(result,method,allowed) if explain else result
        if filtered:
            info=filter_info(app.state.catalog,catalog_scope,year)
            for step in result['trace']:
                if step['tool']=='核心检索':step.update(catalog=info['count'],eligible=info['eligible'],scoring_catalog=len(selected.catalog))
            result=result|{'catalog_scope':catalog_scope,'filters':info,'trace':[{'tool':'目录与年份筛选',**info},*result['trace']]}
            if explain:
                result['feedback'].update(topics=[info['label']] if catalog_scope not in ('core','all') else result['feedback']['topics'],catalog=info['count'],eligible=info['eligible'],excluded=info['count']-info['eligible'],scope=info['label']+'；'+str(year or '全部年份')+'；收录主题不是完整语义标签。筛选在前十截断前生效。')
        if catalog_scope=='all':result={**result,'catalog_scope':'all'}
        if bridge:result={**result,'query_plan':bridge,'trace':[{'tool':'中文术语辅助','original_need':bridge['original_need'],'proposed_query':bridge['proposed_query'],'executed_query':q,'edited':bridge['edited'],'glossary_version':bridge['glossary_version'],'glossary_sha256':bridge['glossary_sha256']},*result['trace']]}
        return result
    app.state.search_feedback=adapter
    app.state.core_search_feedback=core_adapter
