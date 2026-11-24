"""Read-only sealing for a CSS-only visual release."""
import ast
import hashlib
import json
from pathlib import Path
import sqlite3
import urllib.request
import urllib.error

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/stage75'


def read(path):return json.loads(path.read_text(encoding='utf8'))
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    for name in ['browser-validation','http-validation']:assert read(OUT/(name+'.json'))['status']=='passed'
    frozen=read(OUT/'before.json')
    for name,h in frozen.items():assert digest(ROOT/name)==h,name
    old_sources=read(ROOT/'reports/stage74/before.json')
    for name,h in old_sources.items():assert digest(ROOT/name)==h,name
    op=urllib.request.build_opener(urllib.request.ProxyHandler({}));pages=[]
    for port,paths in [(8791,['/','/index.html','/online.html','/evidence.html','/minionerec.html','/sid-lab.html','/legal.html']),(8802,['/','/evaluation.html','/label'])]:
        for path in paths:
            with op.open(f'http://127.0.0.1:{port}'+path,timeout=15) as response:
                body=response.read().decode();assert response.status==200 and body.count('/graphic-colors.css?v=75.1')==1
                pages.append(str(port)+path)
        with op.open(f'http://127.0.0.1:{port}/graphic-colors.css',timeout=15) as response:assert response.read()==(ROOT/'research75/graphic-colors.css').read_bytes()
    with op.open('http://127.0.0.1:8802/api/evaluation/summary',timeout=15) as response:evaluation=json.load(response)
    assert evaluation['algorithm']['human_submitted_pairs']==0 and evaluation['algorithm']['quality_scores'] is None
    assert [evaluation['agent']['methods'][p]['protocol_completed'] for p in ['fixed','llm_agent','constrained']]==[4,0,3]
    assert sum(m['model_calls'] for m in evaluation['agent']['methods'].values())==53
    with op.open('http://127.0.0.1:8791/api/experiments',timeout=15) as response:assert json.load(response)==read(ROOT/'deploy/stage66/evidence-data.json')
    with op.open('http://127.0.0.1:8802/lab/activity',timeout=15) as response:assert not any(j['status']=='running' for j in json.load(response)['jobs'])
    assert not list((ROOT/'data/stage75-lab').rglob('input.json')) and not list((ROOT/'data/stage75-custom/jobs').glob('*/input.json'))
    path=ROOT/'data/stage73-evaluation/work/annotations.sqlite3'
    with sqlite3.connect('file:'+path.as_posix()+'?mode=ro',uri=True) as db:assert db.execute("SELECT count(*) FROM annotation_records WHERE json_extract(body,'$.origin')='human'").fetchone()[0]==0
    try:op.open('http://127.0.0.1:9327/json/version',timeout=2)
    except (urllib.error.URLError,TimeoutError):pass
    else:raise AssertionError('Dedicated browser still open')
    for name,text in [('project-agent.cmd','research75.control'),('papertrail-workbench.cmd','scripts.research75_workbench_control')]:assert text in (ROOT/name).read_text()
    for p in (ROOT/'research75').glob('*.py'):ast.parse(p.read_text(encoding='utf8'))
    paths=[p for p in (ROOT/'research75').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    paths += [p for p in OUT.iterdir() if p.is_file() and p.name!='final-validation.json']
    paths += [ROOT/'scripts/run_research75_workbench.py',ROOT/'scripts/research75_workbench_control.py',ROOT/'docs/GRAPHIC_COLORS_V75.md',ROOT/'project-agent.cmd',ROOT/'papertrail-workbench.cmd']
    result={'status':'passed','date':'2026-11-17','scope':'site-wide graphic color overlay, neutral surfaces retained','html_routes':pages,
            'shared_css_sha256':digest(ROOT/'research75/graphic-colors.css'),'browser_checks':read(OUT/'browser-validation.json')['checks'],
            'preserved_frozen_files':len(frozen),'preserved_original_evidence_sources':len(old_sources),
            'new_model_submissions':0,'new_feedback_writes':0,'human_labels':0,'quality_scores':None,
            'historical_protocol_completed':{'fixed':4,'llm_agent':0,'constrained':3},'historical_model_calls':53,
            'new_dependencies':False,'catalog_expansion':False,'new_training':False,'dedicated_browser_closed':True,'screenshots_viewed':True,
            'files':{str(p.relative_to(ROOT)):digest(p) for p in sorted(paths)}}
    (OUT/'final-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='files'},ensure_ascii=False))


if __name__=='__main__':main()
