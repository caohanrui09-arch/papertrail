"""Independent local v2 search and source reader; no feedback or original service writes."""
from datetime import datetime
import json
from pathlib import Path
from types import SimpleNamespace
from threading import RLock
from typing import Literal
import os
import base64,hashlib
import numpy as np
from fastapi import FastAPI,HTTPException,Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel
from sklearn.preprocessing import normalize
from gsearch.content_recommendation import PARAMS
from gsearch.quality_protocol import digest
from gsearch.unified_search import AsOfBM25
from gsearch import metadata_fetch as mf
from scripts.build_search_v2 import ROOT,TOPICS,AT,load


class SearchV2:
 def __init__(self):
  rows=load(ROOT/'documents.json');receipt=load(ROOT/'catalog-receipt.json')
  assert digest(ROOT/'documents.json')==receipt['documents_sha256']
  self.by_id={p['doc_id']:p for p in rows};self.ids=sorted(self.by_id);self.pos={d:i for i,d in enumerate(self.ids)}
  self.scenes=load(ROOT/'synthetic-scenarios-reviewed.json')
  self.review=load(Path('data/stage30-search-review/review.json'))
  assert self.review['catalog_sha256']==receipt['documents_sha256']
  self.grades={(r['topic'],r['doc_id']):r for r in self.review['judgments']}
  args=dict(PARAMS);args['ngram_range']=tuple(args['ngram_range'])
  self.vectorizer=TfidfVectorizer(**args)
  self.docs=self.vectorizer.fit_transform([self.by_id[d]['title']+'\n'+self.by_id[d]['abstract'] for d in self.ids])
  self.model=SimpleNamespace(catalog=self.ids,by_id=self.by_id,cutoff=datetime.fromisoformat('1990-01-01T00:00:00+00:00'),
   available=np.array([datetime.fromisoformat(self.by_id[d]['available_at']).timestamp() for d in self.ids]),
   sar=SimpleNamespace(seen={'paired':set(self.scenes['shared_seen_filter'])}))
  self.bm25=AsOfBM25(self.model);self.lock=RLock()
  parser=mf.upstream()
  for raw_path in {r['provenance']['raw_path'] for r in rows}:
   raw=Path(raw_path);parsed={p.entry_id.rsplit('/',1)[-1]:p for p in parser._feed.parse(raw.read_bytes()).results}
   for r in rows:
    if r['provenance']['raw_path']!=raw_path:continue
    assert digest(raw)==r['provenance']['raw_sha256']
    actual=parsed[r['doc_id']+'v1'];assert actual.title==r['title'] and actual.summary==r['abstract']

 def paper(self,doc: str) -> dict:
  if doc not in self.by_id:raise HTTPException(404,'此ID不在搜索v2目录')
  r=self.by_id[doc];assert digest(Path(r['provenance']['raw_path']))==r['provenance']['raw_sha256']
  return {k:r[k] for k in ['doc_id','title','abstract','version_key','source_url','available_at','source_verified']}

 def search(self,topic: str,query: str,method: str,context: str) -> dict:
  exact=query.strip()==TOPICS[topic]['core'];trace=[]
  with self.lock:
   base=self.bm25.search('paired',AT,query,10)['papers']
   q=self.vectorizer.transform([query]);scores=linear_kernel(q,self.docs).ravel()
   if method=='tfidf':
    candidates=[d for d in self.ids if d not in self.model.sar.seen['paired'] and scores[self.pos[d]]>0]
    ranked=sorted(candidates,key=lambda d:(-scores[self.pos[d]],d))[:10]
   else:ranked=[r['doc_id'] for r in base]
   trace.append({'tool':'核心检索','method':method,'returned':len(ranked),'catalog':42,'eligible':36})
   original=list(ranked)
   if context!='none' and ranked:
    history=self.scenes[context][topic]
    h=normalize(np.asarray(self.docs[[self.pos[d] for d in history]].sum(axis=0)))
    mixed=normalize(.7*q.toarray()+.3*h);scores=linear_kernel(mixed,self.docs).ravel()
    ranked=sorted(ranked,key=lambda d:(-scores[self.pos[d]],original.index(d)))
    assert set(ranked)==set(original)
    trace.append({'tool':'候选内画像排序','context':context,'history_ids':history,'same_candidates':True,'synthetic':True})
   elif method=='bm25':scores=None
   papers=[]
   for rank,d in enumerate(ranked,1):
    p=self.by_id[d];papers.append({'doc_id':d,'title':p['title'],'version_key':p['version_key'],'source_url':p['source_url'],
     'rank':rank,'review':self.grades[topic,d] if exact else None})
   trace.append({'tool':'审查说明','applies':exact,'used_for_ranking':False,'origin':'model_review'})
   return {'papers':papers,'trace':trace,'query':query,'topic':topic,'review_applies':exact,
    'message':'未找到有词项匹配的候选' if not papers else ('以下为模型摘要审查，非独立真人评价' if exact else '自定义查询：预设主题等级不适用'),
    'candidate_ids_before_rerank':original,'history':[] if context=='none' else [self.paper(d) for d in self.scenes[context][topic]]}


def create_app() -> FastAPI:
 engine=SearchV2();app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
 @app.middleware('http')
 async def headers(request,call_next):
  response=await call_next(request)
  importmap='{"imports":{"preact":"/vendor/preact.mjs","preact/hooks":"/vendor/hooks.mjs","htm":"/vendor/htm.mjs"}}'
  integrity=base64.b64encode(hashlib.sha256(importmap.encode()).digest()).decode()
  response.headers.update({'Content-Security-Policy':f"default-src 'self'; script-src 'self' 'sha256-{integrity}'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Cache-Control':'no-store'})
  return response
 @app.get('/api/health')
 def health():return {'status':'ready','catalog':42,'llm_enabled':False,'instance_id':os.environ.get('GSEARCH_WORKBENCH_INSTANCE','manual')}
 @app.get('/api/meta')
 def meta():return {'topics':TOPICS,'rules':engine.review['rules'],'summary':engine.review['summary'],'at':AT,'catalog':42,'synthetic':True}
 @app.get('/api/search')
 def search(topic:Literal['generative','cold','bias'],q:str=Query(min_length=1,max_length=1000),method:Literal['bm25','tfidf']='bm25',context:Literal['none','same','cross']='none'):
  if not q.strip():raise HTTPException(422,'请输入查询')
  return engine.search(topic,q,method,context)
 @app.get('/api/paper/{doc}')
 def paper(doc:str):return {'paper':engine.paper(doc),'trace':[{'tool':'读取官方原v1摘要','doc_id':doc,'source_verified':True}]}
 app.mount('/',StaticFiles(directory=Path('web/papertrail-v30/dist').resolve(),html=True),name='search-v2')
 return app


def main():
 import uvicorn
 from threadpoolctl import threadpool_limits
 with threadpool_limits(limits=1):uvicorn.run(create_app(),host='127.0.0.1',port=8770,access_log=False,ws='none')


if __name__=='__main__':main()
