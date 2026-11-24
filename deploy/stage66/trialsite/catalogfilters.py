"""Scope adapters over existing metadata and SQLite scoring, before top-k."""
import json
import re
from typing import Literal
Scope=Literal['all','core','multimodal','generative','cold','bias','unclassified']
LABELS={'all':'全部目录','core':'历史核心','multimodal':'多模态快慢思考','generative':'生成式检索','cold':'推荐冷启动','bias':'曝光与评价','unclassified':'未分组'}
def groups(c,doc):
    if doc in c.supplement_ids:return ['multimodal']
    values=[v for v in c.by_id[doc]['discovery_topics'] if v in ('generative','cold','bias')]
    return values or ['unclassified']
def scoped_ids(c,scope:Scope,year:int|None=None)->set[str]:
    return {d for d in c.catalog if (scope=='all' or scope=='core' and d in c.core.by_id or scope in groups(c,d)) and (year is None or int(c.by_id[d]['published_at'][:4])==year)}
def filter_info(c,scope,year):
    ids=scoped_ids(c,scope,year)
    return {'catalog_scope':scope,'label':LABELS[scope],'year':year,'count':len(ids),'eligible':len(ids-c.model.sar.seen['paired']),
        'membership':'既有收录主题，可能重叠；不是人工相关性标签','before_top_k':True,'scoring':'保留所选原目录的IDF，只在取前十前过滤'}
def collections(c):
    return {'scopes':[{'value':k,'label':v,'count':len(scoped_ids(c,k))} for k,v in LABELS.items()],
        'years':sorted({int(c.by_id[d]['published_at'][:4]) for d in c.catalog},reverse=True)}
def filtered_bm25(index,at,query,allowed):
    words=list(dict.fromkeys(re.findall(r'\w+',query.casefold())))[:128]
    stop={'a','an','the','is','are','of','to','in','and','or','that','with','for','by'}
    expression=' OR '.join('"'+w+'"' for w in words if w not in stop)
    if not expression or not allowed:return []
    with index.lock:
        db,_=index._snapshot(at)
        # Same FTS5 porter index, weights, tie-break and top-k as the pinned adapter.
        # json_each is native SQLite; collection/seen predicates precede LIMIT.
        rows=db.execute('SELECT doc_id FROM docs WHERE docs MATCH ? AND doc_id IN (SELECT value FROM json_each(?)) AND doc_id NOT IN (SELECT value FROM json_each(?)) ORDER BY bm25(docs,0,2,1),doc_id LIMIT 10',
            (expression,json.dumps(sorted(allowed)),json.dumps(sorted(index.model.sar.seen['paired'])))).fetchall()
    return [r[0] for r in rows]
