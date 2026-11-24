"""Public package provenance and OSV query; retain failures rather than infer safety."""
from datetime import datetime, timezone
import importlib.metadata as metadata
import hashlib
import json
from pathlib import Path
import re
import sys
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
BUNDLE=ROOT/'deploy/stage39'
OUT=ROOT/'reports/stage39'


def get(url: str, payload=None):
    body=json.dumps(payload).encode() if payload is not None else None
    req=urllib.request.Request(url,data=body,headers={'User-Agent':'Papertrail-dependency-review/1.0','Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=30) as response:return json.load(response)


def main():
    distributions=sorted(metadata.distributions(),key=lambda d:d.metadata['Name'].casefold())
    lock=(BUNDLE/'requirements.lock').read_text()
    pinned=dict(re.findall(r'^([\w-]+)==([^\s\\]+)',lock,re.M))
    actual={d.metadata['Name'].replace('_','-').lower():d.version for d in distributions}
    if {k.lower():v for k,v in pinned.items()} != actual: raise ValueError('Isolated runtime differs from deploy lock')
    docs=[(BUNDLE/'web/vendor'/name).read_text(encoding='utf-8') for name in
          ['PREACT_LICENSE','HTM_LICENSE','ANIME_LICENSE.md','REACT_BITS_LICENSE.md','HIGHLIGHT_WORDS_LICENSE']]
    combined=['Papertrail trial: full third-party notices; generated from installed locked distributions.',
              'Frontend: Preact 11.1.0, HTM 3.1.1, Anime.js 4.5.0, highlight-words-core 2.0.0; React Bits Spotlight derivative subject to MIT + Commons Clause.']+docs
    packages=[]
    for dist in distributions:
        name=dist.metadata['Name'];version=dist.version
        pkg={'name':name,'version':version,'license_expression':dist.metadata.get('License-Expression'),
             'license_classifiers':[c for c in dist.metadata.get_all('Classifier',[]) if c.startswith('License ::')],
             'project_urls':dist.metadata.get_all('Project-URL',[]),'license_files':[]}
        combined.append('\n\n===== '+name+' '+version+' =====\n'+(pkg['license_expression'] or '')+'\n')
        for file in dist.files or []:
            if '.dist-info/' in str(file).replace('\\','/') and re.search(r'license|copying|notice|authors',str(file),re.I):
                path=Path(dist.locate_file(file))
                if path.is_file():
                    raw=path.read_bytes()
                    pkg['license_files'].append({'file':str(file),'sha256':hashlib.sha256(raw).hexdigest()})
                    combined.append(str(file)+'\n'+raw.decode('utf-8',errors='replace'))
        if not pkg['license_files']: raise ValueError('Missing installed license: '+name)
        packages.append(pkg)
    (BUNDLE/'web/open-source.txt').write_text('\n'.join(combined)+'\n',encoding='utf-8')
    query={'queries':[{'package':{'ecosystem':'PyPI','name':p['name']},'version':p['version']} for p in packages]}
    result={'queried_at':datetime.now(timezone.utc).isoformat(),'packages':packages,'python':sys.version,
            'osv_endpoint':'https://api.osv.dev/v1/querybatch','osv_query':query}
    try:
        response=get(result['osv_endpoint'],query)
        result['osv_response']=response
        result['advisories']=[{'package':p['name'],'version':p['version'],'ids':[v['id'] for v in r.get('vulns',[])]}
                              for p,r in zip(packages,response['results']) if r.get('vulns')]
    except Exception as exc:
        result['osv_error']=type(exc).__name__+': '+str(exc)
    for repo in ['alisaifee/limits','laurentS/slowapi','lukasschwab/arxiv.py','render-examples/fastapi']:
        try:
            data=get('https://api.github.com/repos/'+repo)
            result.setdefault('github',[]).append({k:data.get(k) for k in ['full_name','archived','pushed_at','default_branch','license','html_url']})
        except Exception as exc:result.setdefault('github',[]).append({'repo':repo,'error':str(exc)})
    (OUT/'dependency-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print({'locked_packages':len(packages),'license_file_count':sum(len(p['license_files']) for p in packages),
           'advisories':result.get('advisories'),'osv_error':result.get('osv_error'),'notice_bytes':(BUNDLE/'web/open-source.txt').stat().st_size})


if __name__=='__main__':main()
