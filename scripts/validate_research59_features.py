"""Display conversion, native pre-top-k scope filters, source-grounded comparison."""
import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlencode
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'deploy/stage59'))
from trialsite.delivery import create_app
from trialsite.security import Settings
from trialsite.readingview import clean_view
from trialsite.catalogfilters import scoped_ids,groups
from scripts.validate_trial import call,extract
CHECKS=[]
def check(name,value):
    if not value:raise AssertionError(name)
    CHECKS.append(name)
async def main():
    for text,expected in [(r'hello \textbf{bold} and \textit{nested \textbf{text}}','hello bold and nested text'),(r'cost 10\% and \&','cost 10% and &'),(r'math $x^2$ and \(y\)',r'math $x^2$ and \(y\)')]:
        check('native_conversion_'+expected,clean_view(text)['text']==expected)
    for text in [r'\input{session.key}',r'\include{../../secret}',r'\newcommand{\evil}{body}',r'\unknownmacro{meaning}',r'bad \textbf{unclosed']:
        v=clean_view(text);check('unsupported_preserved_'+text,v['text']==text and v['warnings'])
    check('html_is_plain_text',clean_view('<script>alert(1)</script>')['text']=='<script>alert(1)</script>')
    with tempfile.TemporaryDirectory(prefix='features-',dir=ROOT/'.cache/stage59') as folder:
        settings=replace(Settings('https://trial.example',Path(folder)),visitor_per_minute=5000,writes_per_minute=3000,global_per_minute=15000,expensive_per_minute=2000)
        app=create_app(settings);c=app.state.catalog
        async def req(path,who=None,body=None):return await call(app,path,'POST' if body is not None else 'GET',body,who)
        async def search(**extra):return await req('/api/search?'+urlencode(dict(topic='generative',q='multimodal fast slow thinking reasoning',method='bm25',context='none',catalog_scope='multimodal',explain='true')|extra))
        _,previews,_=await req('/api/paper-previews')
        check('all_previews_available',previews['count']==167)
        for doc in sorted(c.supplement_ids):
            _,old,_=await req('/api/paper/'+doc);status,new,h=await req('/api/paper-reading/'+doc)
            check('unchanged_source_'+doc,status==200 and new['paper']==old['paper'])
            check('source_digest_'+doc,new['reading_view']['source_sha256']==hashlib.sha256(old['paper']['abstract'].encode()).hexdigest())
            check('comparison_exact_source_'+doc,all(v is None or v['evidence'] in old['paper']['abstract'] and v['version_key']==old['paper']['version_key'] and v['source_url']==old['paper']['source_url'] for v in new['comparison'].values()))
            check('source_not_cookie_'+doc,'set-cookie' not in h)
            check('supplement_membership_'+doc,previews['papers'][doc]['collections']==['multimodal'])
        _,fast,_=await req('/api/paper-reading/2504.18458')
        check('fast_formatting_removed',r'\textbf' not in fast['reading_view']['text'] and '32.7-67.3%' in fast['reading_view']['text'])
        for doc in ['2504.18458','2506.00806','2610.15810']:
            check('unknown_training_left_empty_'+doc,(await req('/api/paper-reading/'+doc))[1]['comparison']['training'] is None)
        check('known_training_grpo',(await req('/api/paper-reading/2511.16670'))[1]['comparison']['training']['evidence'].startswith('we train'))
        check('known_training_free',(await req('/api/paper-reading/2610.25999'))[1]['comparison']['training']['evidence']=='a training-free, two-stage framework')
        check('unreviewed_core_not_invented',(await req('/api/paper-reading/'+c.catalog[0]))[1]['comparison'] is None)
        check('missing_paper_404',(await req('/api/paper-reading/9999.12345'))[0]==404)
        check('vendored_source_private',(await req('/third-party/pylatexenc/latex2text/__init__.py'))[0]==404)
        for method in ['bm25','tfidf']:
            for year,count in [(None,5),(2025,3),(2026,2),(2024,0)]:
                extra=dict(method=method)
                if year:extra['year']=year
                code,result,_=await search(**extra)
                allowed=scoped_ids(c,'multimodal',year)
                check('actual_scope_'+method+str(year),code==200 and all(p['doc_id'] in allowed for p in result['papers']) and len(result['papers'])==count)
                check('scope_count_'+method+str(year),result['feedback']['catalog']==count and result['filters']['count']==count and result['filters']['before_top_k'])
            for context in ['same','cross']:
                _,result,_=await search(method=method,context=context,year=2026)
                check('rerank_keeps_scope_'+method+context,set(p['doc_id'] for p in result['papers'])=={'2610.15810','2610.25999'})
        for scope in ['generative','cold','bias','unclassified','core','all']:
            _,result,_=await search(catalog_scope=scope,q='learning')
            check('scope_membership_'+scope,all(p['doc_id'] in scoped_ids(c,scope) for p in result['papers']))
        for year in ['hello','1899','2101','2025.5']:
            check('invalid_year_'+year,(await search(year=year))[0]==422)
        # Independent native full-match reference, then apply metadata predicate and take top10.
        recovered=False
        for query in ['learning','model','reasoning','multimodal']:
            with c.bm25.lock:
                db,_=c.bm25._snapshot(c.at)
                ordered=[r[0] for r in db.execute('SELECT doc_id FROM docs WHERE docs MATCH ? ORDER BY bm25(docs,0,2,1),doc_id',('"'+query+'"',)) if r[0] not in c.model.sar.seen['paired']]
            expected=[d for d in ordered if d in c.supplement_ids][:10]
            _,result,_=await search(q=query)
            check('native_before_top10_'+query,[p['doc_id'] for p in result['papers']]==expected)
            recovered |= bool(set(expected)-set(ordered[:10]))
        check('recovers_match_outside_global_top10',recovered)
        _,_,headers=await req('/api/profile');owner=extract(headers)
        base=(await req('/api/profile',owner))[1]
        body=dict(catalog_key=c.catalog_key,revision=0,reason='missing_known_paper',executed_query='multimodal fast slow thinking reasoning',catalog_scope='multimodal',year=2026,expected_paper='2504.18458')
        code,d,_=await req('/api/profile/demands/save',owner,body)
        check('year_exclusion_not_directory_gap',code==200 and d['items'][0]['diagnosis']['code']=='outside_year' and len(d['items'][0]['shown_papers'])==2)
        check('demand_scope_evidence',d['items'][0]['year']==2026 and d['items'][0]['catalog_size']==2 and d['items'][0]['scope_label']=='多模态快慢思考')
        report=dict(catalog_key=c.catalog_key,revision=0,reading_revision=0,notes_revision=0,papers=[dict(doc_id='2610.25999',version_key='arxiv:2610.25999v1')],include_notes=False,search_context={k:v for k,v in body.items() if k in ['executed_query','catalog_scope','year']})
        code,r,_=await req('/api/profile/report/preview',owner,report)
        check('report_keeps_exact_scope_year',code==200 and '多模态快慢思考；年份：2026' in r['markdown'])
        check('display_search_dont_change_profile',(await req('/api/profile',owner))[1]==base)
        check('no_vocabulary_refit',c.vectorizer is c.core.vectorizer and (c.documents[:162]!=c.core.documents).nnz==0)
        c.close()
    (ROOT/'reports/stage59/features-validation.json').write_text(json.dumps({'status':'passed','passed':len(CHECKS),'checks':CHECKS,'scope':'isolated ASGI; display conversion not scientific rewriting; no relevance uplift claim'},ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print({'passed':len(CHECKS)})
if __name__=='__main__':asyncio.run(main())
