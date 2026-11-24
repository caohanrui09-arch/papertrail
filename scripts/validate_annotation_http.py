"""Real HTTP checks with a server-marked automation namespace, not human labels."""
import http.cookiejar
import json
from pathlib import Path
from uuid import uuid4
import urllib.request
import urllib.error

URL='http://127.0.0.1:8769'


class Client:
    def __init__(self):
        self.jar=http.cookiejar.CookieJar()
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(self.jar))

    def call(self,method,path,body=None,test=True,headers=None):
        h={'Content-Type':'application/json',**({'X-Papertrail-Verification':'1'} if test else {}),**(headers or {})}
        req=urllib.request.Request(URL+path,data=json.dumps(body).encode() if body is not None else None,method=method,headers=h)
        try:
            with self.opener.open(req,timeout=60) as r:return r.status,r.read().decode(),{k.lower():v for k,v in r.headers.items()}
        except urllib.error.HTTPError as e:return e.code,e.read().decode(),{k.lower():v for k,v in e.headers.items()}

    def value(self,method,path,body=None,test=True):
        code,text,_=self.call(method,path,body,test)
        assert code==200,(code,text)
        return json.loads(text)


def keys(value):
    if isinstance(value,dict):return set(value)|set().union(*(keys(x) for x in value.values()),set())
    if isinstance(value,list):return set().union(*(keys(x) for x in value),set())
    return set()


def main():
    a,b=Client(),Client();checks=[];private=[]
    def check(name,value=True):assert value,name;checks.append(name)
    w=a.value('GET','/api/annotation/workspace')
    check('only nine tuning requests',len(w['queries'])==9 and w['total_pairs']==155)
    check('real space starts empty',a.value('GET','/api/annotation/workspace',test=False)['submitted']==0)
    qid=w['queries'][0]['query_id'];detail=a.value('GET','/api/annotation/queries/'+qid);aid=detail['candidates'][0]['annotation_id']
    check('blind API omits methods ranks scores users',not (keys(detail)&{'methods','sources','rank','score','user_id','profile_id','runs'}))
    check('original version and text',all(c['paper']['source_verified'] and c['paper']['version']==1 and c['paper']['abstract'] for c in detail['candidates']))
    check('evaluation queries unavailable',a.call('GET','/api/annotation/queries/q25-004')[0]==422)
    base='/api/annotation/judgments/'+qid+'/'+aid
    check('cannot label before confirmation',a.call('PUT',base,{'revision':0,'operation':'draft'})[0]==422)
    review='/api/annotation/reviews/'+qid
    r=a.value('PUT',review,{'revision':0,'operation':'draft','decision':'approve'})
    check('draft review remains locked',not a.value('GET','/api/annotation/queries/'+qid)['labeling_unlocked'])
    final={'revision':1,'operation':'submit','decision':'approve','reviewer':'AUTOMATED_HTTP','note':'Test fixture only; not a human assessment','attest':True}
    check('missing declaration rejected',a.call('PUT',review,{**final,'attest':False})[0]==422)
    r=a.value('PUT',review,final)
    check('test confirmation never tagged human',r['value']['origin']=='automation_test')
    d=a.value('GET','/api/annotation/queries/'+qid);check('approval unlocks matching query',d['labeling_unlocked'])
    check('stale confirmation refused',a.call('PUT',review,final)[0]==409)
    r=a.value('PUT',base,{'revision':0,'operation':'draft','grade':1,'rationale':'draft for persistence test'})
    check('saved draft not a submitted grade',a.value('GET','/api/annotation/workspace')['submitted']==0)
    check('unknown needs a reason',a.call('PUT',base,{'revision':1,'operation':'skip'})[0]==422)
    r=a.value('PUT',base,{'revision':1,'operation':'skip','grade':2,'rationale':'test unknown'})
    check('unknown forced to null',r['value']['grade'] is None and r['value']['status']=='skipped')
    grade={'revision':2,'operation':'submit','grade':2,'reviewer':'AUTOMATED_HTTP','rationale':'Synthetic test judgment; not human relevance','attest':True}
    r=a.value('PUT',base,grade);private.append(r)
    check('valid test submission counted only in test workspace',a.value('GET','/api/annotation/workspace')['submitted']==1 and a.value('GET','/api/annotation/workspace',test=False)['submitted']==0)
    r=a.value('PUT',base,{**grade,'revision':3,'grade':0,'rationale':'Changed synthetic test value'})
    hist=a.value('GET','/api/annotation/history/'+qid+'/judgment/'+aid)
    check('full revision history retained',len(hist)==4 and hist[0]['value']['grade']==0 and hist[1]['value']['grade']==2)
    check('stale grade refused',a.call('PUT',base,grade)[0]==409)
    for bad in (True,'1',3):check('strict grade '+str(bad),a.call('PUT',base,{**grade,'revision':4,'grade':bad})[0]==422)
    a.value('PUT',review,{**final,'revision':2})
    check('new confirmation revision invalidates old submission',a.value('GET','/api/annotation/workspace')['submitted']==0)
    a.value('PUT',base,{**grade,'revision':4})
    check('resubmission binds current confirmation',a.value('GET','/api/annotation/workspace')['submitted']==1)
    a.value('PUT',review,{**final,'revision':3,'decision':'reject'})
    check('rejected query locks judgments',a.call('PUT',base,{**grade,'revision':5})[0]==422)
    check('other cookie has no confirmation',not b.value('GET','/api/annotation/queries/'+qid)['labeling_unlocked'])
    check('other cookie cannot read revision history',b.value('GET','/api/annotation/history/'+qid+'/judgment/'+aid)==[])
    native=a.value('GET','/api/annotation/export');check('native export contains no ranking keys',not (keys(native)&{'methods','sources','rank','score','user_id','profile_id','runs'}))
    a.value('PUT',review,{**final,'revision':4});a.value('PUT',base,{**grade,'revision':5})
    studio=a.value('GET','/api/annotation/export?format=label-studio');anns=[x for t in studio for x in t['annotations']]
    check('Label Studio choice export with explicit test origin',len(anns)==1 and anns[0]['origin']=='automation_test' and len(anns[0]['result'])==2)
    check('private files not statically served',a.call('GET','/data/stage26-annotation/evaluator/runs.json')[0]==404)
    check('foreign mutation refused',a.call('PUT',review,final,headers={'Origin':'https://example.com'})[0]==403)
    code,text,h=a.call('GET','/label')
    check('actual native editor asset referenced',code==200 and '/vendor/jsoneditor.js' in text and 'unsafe-eval' not in h['content-security-policy'])
    check('script asset available',a.call('GET','/vendor/jsoneditor.js')[0]==200)
    check('production workspace remains zero',a.value('GET','/api/annotation/workspace',test=False)['approved']==0 and b.value('GET','/api/annotation/workspace',test=False)['submitted']==0)
    folder=Path('data/stage26-annotation/verification/http')/str(uuid4());folder.mkdir(parents=True)
    (folder/'responses.json').write_text(json.dumps({'native_export':native,'studio_export':studio,'history':hist},ensure_ascii=False,indent=2),encoding='utf-8')
    path=Path('reports/stage26/http-validation-'+folder.name+'.json')
    path.write_text(json.dumps({'status':'passed','count':len(checks),'checks':checks,'private_responses':str(folder),
        'human_records_created':0,'automation_namespace':True},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':'passed','checks':len(checks),'report':str(path)}))


if __name__=='__main__':main()
