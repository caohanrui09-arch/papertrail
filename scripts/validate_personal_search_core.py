"""Real HTTP acceptance: query-label scope, candidate boundaries and original source reader."""
import json
from pathlib import Path
import urllib.request,urllib.error,urllib.parse
from gsearch.quality_protocol import save


def main() -> None:
 out=Path('reports/stage35/core-http-validation.json')
 if out.exists():raise ValueError('Preserve successful acceptance')
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));checks=[]
 def get(path,expected=200,method='GET'):
  try:
   with opener.open(urllib.request.Request('http://127.0.0.1:8777'+path,method=method),timeout=15) as response:
    status=response.status;raw=response.read();headers=response.headers
  except urllib.error.HTTPError as error:status=error.code;raw=error.read();headers=error.headers
  assert status==expected,(path,status)
  checks.append({'path':path,'method':method,'status':status})
  return json.loads(raw) if 'application/json' in headers.get('Content-Type','') else raw
 meta=get('/api/meta');assert meta['catalog']==42
 reserved=set(json.loads(Path('data/stage29-search-v2/synthetic-scenarios-reviewed.json').read_text())['shared_seen_filter'])
 for topic,settings in meta['topics'].items():
  for method in ('bm25','tfidf'):
   baseline=None
   for context in ('none','same','cross'):
    r=get('/api/search?'+urllib.parse.urlencode({'topic':topic,'q':settings['core'],'method':method,'context':context}))
    ids={p['doc_id'] for p in r['papers']}
    assert len(ids)==len(r['papers'])==10 and not ids&reserved and r['review_applies']
    assert all(p['review']['human'] is False and p['review']['origin']=='model_review' for p in r['papers'])
    if baseline is None:baseline=ids
    else:assert ids==baseline
    if context!='none':assert r['trace'][1]['same_candidates'] is True
  first=r['papers'][0]['doc_id'];p=get('/api/paper/'+first)['paper']
  assert p['doc_id']==first and p['abstract'] and p['source_verified'] and p['version_key'].endswith('v1')
 custom=get('/api/search?'+urllib.parse.urlencode({'topic':'generative','q':'book search','context':'same'}))
 assert not custom['review_applies'] and all(p['review'] is None for p in custom['papers'])
 empty=get('/api/search?topic=generative&q=zxqvvv123456zz');assert not empty['papers']
 get('/api/search?topic=unknown&q=test',422);get('/api/search?topic=cold&q=test&method=llm',422)
 get('/api/search?topic=cold&q=test&context=real_user',422);get('/api/search?topic=cold&q=%20',422)
 get('/api/search?topic=cold&q='+'a'*1001,422);get('/api/paper/no-such-document',404)
 get('/api/search?topic=cold&q=test',405,'POST')
 page=get('/');assert b'importmap' in page
 for name in ['main.mjs','styles.css','vendor/preact.mjs','vendor/hooks.mjs','vendor/htm.mjs','vendor/anime.esm.min.js','mark.svg','reading.css','reading.mjs','personal.mjs','personal.css']:assert get('/'+name)
 save(out,{'status':'passed','count':len(checks),'checks':checks,'api_read_only':True,
  'candidate_sets_unchanged_by_context':True,'custom_queries_do_not_inherit_model_labels':True})
 print(json.dumps({'status':'passed','checks':len(checks)}))


if __name__=='__main__':main()
