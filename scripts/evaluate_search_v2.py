"""Separate native topic retrieval from fixed-candidate synthetic profile reranking."""
from datetime import datetime
import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel
from sklearn.preprocessing import normalize
from threadpoolctl import threadpool_limits

from gsearch.content_recommendation import PARAMS
from gsearch.quality_protocol import digest,save
from gsearch.unified_search import AsOfBM25
from gsearch import metadata_fetch as mf
from scripts.build_search_v2 import ROOT,AT,TOPICS,ANCHORS,load


def main() -> None:
 parser=argparse.ArgumentParser();parser.add_argument('--reviewed-context',action='store_true');args_cli=parser.parse_args()
 suffix='-reviewed' if args_cli.reviewed_context else ''
 out=ROOT/('paired-diagnostic'+suffix+'.json')
 if out.exists():raise ValueError('Preserve paired diagnostic')
 rows=load(ROOT/'documents.json');receipt=load(ROOT/'catalog-receipt.json')
 assert digest(ROOT/'documents.json')==receipt['documents_sha256']
 # Native parser re-reads retained official responses; do not substitute snippets.
 package=mf.upstream()
 for p in {r['provenance']['raw_path'] for r in rows}:
  records=[r for r in rows if r['provenance']['raw_path']==p]
  raw=Path(p);assert all(digest(raw)==r['provenance']['raw_sha256'] for r in records)
  parsed={r.entry_id.rsplit('/',1)[-1]:r for r in package._feed.parse(raw.read_bytes()).results}
  for r in records:
   original=parsed[r['doc_id']+'v1'];assert original.title==r['title'] and original.summary==r['abstract']
 ids=sorted(r['doc_id'] for r in rows);by_id={r['doc_id']:r for r in rows};position={d:i for i,d in enumerate(ids)}
 histories={};reserved=set()
 for topic in TOPICS:
  choices=sorted((r['doc_id'] for r in rows if topic in r['discovery_topics'] and not r['anchor_check']),key=lambda d:hashlib.sha256(('search-v2-history:'+d).encode()).hexdigest())
  chosen=[d for d in choices if d not in reserved][:2]
  if args_cli.reviewed_context:
   reviewed=load(ROOT/'reviewed-contexts.json')['contexts'][topic]
   chosen=[r['doc_id'] for r in reviewed]
   for r in reviewed:assert r['evidence'] in by_id[r['doc_id']]['abstract']
  assert len(chosen)==2,'Need two verified history examples per topic'
  histories[topic]=chosen;reserved.update(chosen)
 topics=list(TOPICS)
 save(ROOT/('synthetic-scenarios'+suffix+'.json'),{'origin':'synthetic_content_context','real_user_feedback':False,
  'history_selection':'assistant abstract-reviewed development amendment' if args_cli.reviewed_context else 'two non-anchor hash-selected discovery documents per topic',
  'topic_assignment':'assistant-confirmed related context, not human feedback or relevance qrels' if args_cli.reviewed_context else 'discovery query match, not human-confirmed semantic relevance',
  'same':histories,'cross':{t:histories[topics[(i+1)%3]] for i,t in enumerate(topics)},
  'shared_seen_filter':sorted(reserved)})
 model=SimpleNamespace(catalog=ids,by_id=by_id,cutoff=datetime.fromisoformat('1990-01-01T00:00:00+00:00'),
  available=np.array([datetime.fromisoformat(by_id[d]['available_at']).timestamp() for d in ids]),sar=SimpleNamespace(seen={'paired':reserved}))
 args=dict(PARAMS);args['ngram_range']=tuple(args['ngram_range'])
 # A separate v2 representation fits only this pre-asof v2 catalog.
 vectorizer=TfidfVectorizer(**args)
 full=load(Path('data/stage26-annotation/blind/tasks.json'))
 diagnostic=[];searcher=AsOfBM25(model)
 with threadpool_limits(limits=1):
  docs=vectorizer.fit_transform([by_id[d]['title']+'\n'+by_id[d]['abstract'] for d in ids])
  try:
   for i,topic in enumerate(topics):
    text=TOPICS[topic]['core'];q=vectorizer.transform([text])
    core=searcher.search('paired',AT,text,10)['papers'];candidate_ids=[p['doc_id'] for p in core]
    query_scores=linear_kernel(q,docs).ravel()
    eligible=[d for d in ids if d not in reserved]
    tfidf=sorted(eligible,key=lambda d:(-query_scores[position[d]],d))[:10]
    reranks={}
    for condition,history in [('query_only',[]),('same',histories[topic]),('cross',histories[topics[(i+1)%3]])]:
     context=normalize(np.asarray(docs[[position[d] for d in history]].sum(axis=0))) if history else np.zeros((1,docs.shape[1]))
     mixed=normalize(.7*q.toarray()+.3*context) if history else q
     scores=linear_kernel(mixed,docs).ravel()
     ranked=sorted(candidate_ids,key=lambda d:(-scores[position[d]],candidate_ids.index(d)))
     assert set(ranked)==set(candidate_ids) and not set(ranked)&reserved
     reranks[condition]=[{'doc_id':d,'score':float(scores[position[d]]),'source_url':by_id[d]['source_url']} for d in ranked]
    qid=['q25-001','q25-007','q25-010'][i]
    verbose=searcher.search('paired',AT,full[qid]['query']['request'],10)['papers']
    relevant_anchors={'generative':ANCHORS[:2],'cold':[ANCHORS[2]],'bias':ANCHORS[3:]}[topic]
    diagnostic.append({'topic':topic,'core_text':text,'development_query':qid,'full_request_bm25':verbose,
      'core_bm25':core,'core_tfidf':[{'doc_id':d,'score':float(query_scores[position[d]])} for d in tfidf],
      'fixed_candidate_reranking':reranks,
      'anchor_regression_only':{d:{'present':d in by_id,'core_bm25_rank':candidate_ids.index(d)+1 if d in candidate_ids else None,
         'core_tfidf_rank':tfidf.index(d)+1 if d in tfidf else None} for d in relevant_anchors}})
  finally:searcher.close()
 save(out,{'origin':'development_diagnostic','quality_metrics_computed':False,'human_labels':0,'weights_tuned':False,
  'ranking_scope':'only core BM25 top10; same/cross share identical candidates and seen union',
  'document_count':len(rows),'source_versions_verified':len(rows),'catalog_sha256':digest(ROOT/'documents.json'),
  'history_documents':len(reserved),'scenarios':diagnostic})
 lines=['# 搜索v2：开发链路结果','','原始需求、核心主题检索、同主题与跨主题候选内排序分别保存。全部是开发诊断，非真人相关性评价。','']
 for s in diagnostic:
  lines += ['## '+s['topic'],'', '核心检索：'+s['core_text'],'']
  for p in s['core_bm25']:
   r=by_id[p['doc_id']];lines += [f"### {r['title']}",'',f"{r['version_key']} · {r['source_url']}",'',r['abstract'],'']
 (ROOT/('核心检索与原摘要'+suffix+'.md')).write_text('\n'.join(lines),encoding='utf-8')
 print(json.dumps({'documents':len(rows),'verified_versions':len(rows),'paired_scenarios':6,'candidate_sets_preserved':True,
  'anchor_checks':{s['topic']:s['anchor_regression_only'] for s in diagnostic}},ensure_ascii=False))


if __name__=='__main__':main()
