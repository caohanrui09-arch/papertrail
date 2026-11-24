"""Verify raw text/date identity for every preview and exact unchanged search responses."""
from datetime import datetime
import json
from pathlib import Path
import urllib.parse
import urllib.request
from gsearch.quality_protocol import save


def main():
    checks=[]
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def get(port,path):
        with opener.open(f'http://127.0.0.1:{port}'+path,timeout=20) as r:
            assert r.headers.get('Cache-Control')=='no-store'
            data=json.load(r)
        checks.append({'port':port,'path':path})
        return data
    meta=get(8780,'/api/meta');previews=get(8780,'/api/paper-previews')
    docs=json.loads(Path('data/stage29-search-v2/documents.json').read_text(encoding='utf-8'))
    assert previews['count']==len(previews['papers'])==len(docs)==42
    for row in docs:
        p=previews['papers'][row['doc_id']]
        original=get(8780,'/api/paper/'+row['doc_id'])['paper']
        assert p['abstract_excerpt']==original['abstract'][:len(p['abstract_excerpt'])]
        assert 0<len(p['abstract_excerpt'])<=420
        assert p['excerpt_truncated']==(len(p['abstract_excerpt'])<len(original['abstract']))
        assert p['submitted_year']==datetime.fromisoformat(row['published_at']).year
        assert p['published_at']==row['published_at'] and p['date_kind']=='arxiv_first_submission'
        assert p['available_at']==row['available_at']
        assert all(p[k]==original[k] for k in ('doc_id','title','version_key','source_url','source_verified'))
    compared=[]
    for topic,settings in meta['topics'].items():
        for method in ('bm25','tfidf'):
            for context in ('none','same','cross'):
                path='/api/search?'+urllib.parse.urlencode(dict(topic=topic,q=settings['core'],method=method,context=context))
                old,new=get(8779,path),get(8780,path)
                assert old==new, (topic,method,context)
                compared.append({'topic':topic,'method':method,'context':context,'response_equal':True})
    save(Path('reports/stage38/preview-validation.json'),{'status':'passed','preview_count':42,'all_exact_original_prefixes':True,
        'date_semantics':'raw arxiv v1 published field, not journal publication or retrieval year','unchanged_search_responses':compared,
        'http_count':len(checks),'checks':checks,'preferences_modified':False})
    print(json.dumps({'status':'passed','original_previews':42,'unchanged_responses':len(compared),'http_requests':len(checks)}))


if __name__=='__main__':main()
