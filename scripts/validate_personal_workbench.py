"""Real HTTP acceptance with independent cookie jars; no invented human labels."""
import http.cookiejar
import json
from pathlib import Path
import urllib.request
import urllib.error
from uuid import uuid4
import math

URL='http://127.0.0.1:8768'


class BrowserSession:
    def __init__(self):
        self.jar=http.cookiejar.CookieJar()
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(self.jar))

    def call(self,method,path,body=None,headers=None):
        req=urllib.request.Request(URL+path,data=json.dumps(body).encode() if body is not None else None,
            method=method,headers={'Content-Type':'application/json',**(headers or {})})
        try:
            with self.opener.open(req,timeout=120) as r:return r.status,r.read().decode(),dict(r.headers)
        except urllib.error.HTTPError as e:return e.code,e.read().decode(),dict(e.headers)

    def value(self,method,path,body=None):
        code,text,_=self.call(method,path,body)
        assert code==200,(code,text)
        return json.loads(text)

    def run(self,mode='search',query='diffusion models',profile='personal'):
        code,text,_=self.call('POST','/api/runs',{'thread_id':str(uuid4()),'mode':mode,'query':query,'profile':profile,'origin':'verification'})
        assert code==200,(code,text)
        events=[json.loads(x) for x in text.splitlines()]
        assert events[-1]['type']=='done' and events[-1]['run']['status'] in ('completed','no_results','partial'),events[-1]
        assert len([e for e in events if e['type']=='tool_result'])==len(events[-1]['run']['trace'])
        return events[-1]['run']


def hits(run,tool='recommend_papers'):
    return next(e['result']['papers'] for e in run['trace'] if e['tool']==tool)


def main():
    checks=[];runs=[]
    def check(label,truth=True):
        assert truth,label
        checks.append(label)
    a,b=BrowserSession(),BrowserSession()
    a.value('GET','/api/config');b.value('GET','/api/config')
    check('independent cookie identities',list(a.jar)[0].value!=list(b.jar)[0].value)
    check('empty new visitor',a.value('GET','/api/profile')['items']==[])
    cold=a.run('recommend','');runs.append(cold)
    check('explicit cold fallback',hits(cold)[0]['explanation']['kind']=='popularity_fallback')
    search=a.run();runs.append(search);seed=hits(search,'search_papers')[0]['doc_id']
    def feedback(doc,value,revision,run=search):
        return a.value('POST','/api/profile/feedback',{'doc_id':doc,'value':value,'revision':revision,'run_id':run['id']})
    liked=feedback(seed,'like',0)
    check('persisted like',liked['revision']==1 and liked['items'][0]['preference']=='like')
    check('other visitor stays empty',b.value('GET','/api/profile')['items']==[])
    check('revision conflict rejected',a.call('POST','/api/profile/feedback',{'doc_id':seed,'value':'hide','revision':0})[0]==409)
    rec=a.run('recommend','');runs.append(rec);papers=hits(rec)
    check('like changes ranking',[p['doc_id'] for p in papers]!=[p['doc_id'] for p in hits(cold)])
    check('liked item excluded',seed not in [p['doc_id'] for p in papers])
    for paper in papers:
        e=paper['explanation']
        check('explanation contribution identity '+paper['doc_id'],e['kind']=='content_similarity' and
            math.isclose(e['all_term_contribution_sum'],paper['score'],abs_tol=1e-12) and
            math.isclose(e['all_anchor_contribution_sum'],paper['score'],abs_tol=1e-12) and e['anchors'][0]['doc_id']==seed)
    blocked=papers[0]['doc_id'];hidden=feedback(blocked,'hide',1,rec)
    after=a.run('mixed');runs.append(after)
    check('hide filters search and recommendation',all(blocked not in [p['doc_id'] for p in e['result'].get('papers',[])] for e in after['trace']))
    check('mixed fixed protocol preserved',len(after['trace'])==5 and len(after['answer']['citations'])==2)
    check('current snapshot version',after['profile_revision']==2)
    for path in [f"/api/runs/{rec['id']}/export",f"/api/runs/{rec['id']}/papers/{papers[1]['doc_id']}",f"/api/runs/{rec['id']}/cancel"]:
        check('other visitor cannot access '+path,b.call('GET' if path.endswith('export') else 'POST',path)[0]==404)
    check('other visitor cannot access thread',b.value('GET','/api/threads/'+rec['thread_id'])==[])
    check('no owner or raw private task in export',all(not k.startswith('_') for k in a.value('GET',f"/api/runs/{rec['id']}/export")))
    # Undo and reset do not rewrite old run snapshots or old source replay.
    feedback(blocked,'none',2,rec)
    reset=a.value('POST','/api/profile/reset',{'revision':3})
    check('reset empty with monotonic revision',reset=={'revision':4,'items':[],'scope':'当前浏览器个人空间；当下偏好作用于冻结历史目录，不是历史质量评价'})
    source=a.value('POST',f"/api/runs/{rec['id']}/papers/{papers[1]['doc_id']}")
    check('old source replay uses old snapshot after reset',source['paper']['source_verified'] and source['new_source_session'] and len(source['trace'])==2)
    cached=a.value('POST',f"/api/runs/{rec['id']}/papers/{papers[1]['doc_id']}")
    check('cached source executes no new calls',cached['cached_original'] and cached['trace']==[])
    resetrec=a.run('recommend','');runs.append(resetrec)
    check('reset restores fallback ranking',[p['doc_id'] for p in hits(resetrec)]==[p['doc_id'] for p in hits(cold)])
    check('unreturned feedback refused',a.call('POST','/api/profile/feedback',{'doc_id':seed,'value':'like','revision':4})[0]==403)
    check('foreign origin refused',a.call('POST','/api/profile/reset',{'revision':4},{'Origin':'https://example.com'})[0]==403)
    check('cross-site read refused',a.call('GET','/api/profile',headers={'Sec-Fetch-Site':'cross-site'})[0]==403)
    check('unknown preference value refused',a.call('POST','/api/profile/feedback',{'doc_id':seed,'value':'other','revision':4})[0]==422)
    check('no private static files',a.call('GET','/data/stage24-personal/preferences.sqlite3')[0]==404)
    quality=a.value('GET','/api/quality-status');check('human status available',isinstance(quality,dict))
    warm=a.run('recommend','',profile='warm');runs.append(warm);check('frozen warm demo retained',len(warm['trace'])==3)
    private=Path('data/stage24-personal/validation')/str(uuid4());private.mkdir(parents=True)
    (private/'runs.json').write_text(json.dumps(runs,ensure_ascii=False,indent=2),encoding='utf-8')
    out={'status':'passed','checks':checks,'count':len(checks),'quality_status':quality,'private_artifacts':str(private),'real_http':True,'human_judgments_created':0}
    path=Path('reports/stage24/http-validation.json')
    if path.exists():path=path.with_name('http-validation-'+str(uuid4())+'.json')
    path.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':'passed','checks':len(checks),'report':str(path)}))


if __name__=='__main__':main()
