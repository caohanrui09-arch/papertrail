"""Thin presentation adapter over the frozen fixed policy and real local API."""
import argparse
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import tempfile
from .quality_protocol import digest,save
from .showcase import choose_user,fenced
from .unified_agent import run,request

ROOT=Path('data/stage22-delivery')
ASOF='2025-02-23T05:28:26.401006+00:00'


def select_task(query: str | None = None) -> tuple[dict,dict]:
    rows=json.loads(Path('data/stage13-expansion/documents.json').read_text(encoding='utf-8'))
    cutoff=json.loads(Path('reports/stage13/admission-plan.json').read_text())['cutoff']
    warm={r['doc_id'] for r in rows if r['cohort']=='warm'}
    seen={};users=set()
    with Path('data/stage9-recommendation/train.csv').open(encoding='utf-8',newline='') as stream:
        for r in csv.DictReader(stream):
            seen.setdefault(r['user_id'],set()).add(r['arxiv_id'])
            if float(r['rating'])==1 and r['arxiv_id'] in warm:users.add(r['user_id'])
    user=choose_user(sorted(users))
    eligible=[r for r in rows if r['doc_id'] in warm and r['doc_id'] not in seen[user]
        and datetime.fromisoformat(r['available_at'])<=datetime.fromisoformat(cutoff)]
    selected=min(eligible,key=lambda r:hashlib.sha256(('stage22-query:'+r['doc_id']).encode()).hexdigest())
    actual=selected['title'] if query is None else query
    if not isinstance(actual,str) or not actual.strip() or len(actual)>2000:raise ValueError('Nonempty query up to2000 characters required')
    task={'id':'portfolio-fixed-mixed','user_id':user,'at':ASOF,'intent':'mixed','query':actual,
        'instruction':'Search, recommend a different paper from my frozen history, read both v1 abstracts, and cite both.'}
    selection={'user_rule':'existing stage16 choose_user hash over train-positive warm-catalog profile users',
        'query_rule':'hash over unseen warm catalog at training cutoff; no rank or future-feedback selection' if query is None else 'user_supplied',
        'known_item_query':query is None,'query_source_doc_id':selected['doc_id'] if query is None else None,
        'training_seen_count':len(seen[user]),'future_feedback_read':False,
        'documents_sha256':digest(Path('data/stage13-expansion/documents.json')),
        'train_sha256':digest(Path('data/stage9-recommendation/train.csv'))}
    return task,selection


def validate_run(raw: dict) -> dict:
    if not raw['completed_protocol'] or not raw.get('answer'):raise ValueError('Fixed policy did not finalize')
    events=raw['trace']['trace']
    if [e['tool'] for e in events]!=['search_papers','recommend_papers','read_paper','read_paper','finalize']:
        raise ValueError('Expected real search/recommend/two-read/finalize chain')
    if any('error' in e['result'] for e in events):raise ValueError('Tool error in demonstration')
    if events[1]['result']['cold_user_fallback'] is not False:raise ValueError('Expected a real training profile')
    reads={e['result']['doc_id']:e['result'] for e in events if e['tool']=='read_paper'}
    citations=raw['answer']['citations']
    if len(reads)!=2 or len(citations)!=2:raise ValueError('Two distinct originals required')
    for citation in citations:
        original=reads.get(citation['doc_id'])
        if not original or citation['version']!=1 or not original.get('source_verified'):
            raise ValueError('Unverified original/version')
        if citation['quote'] not in original['abstract'] or not citation['quote']:
            raise ValueError('Quote not in read abstract')
        for key in ('version','version_key','title','source_url'):
            if citation[key]!=original[key]:raise ValueError('Citation identity drift')
    if 'search_papers' not in citations[0]['retrieved_by'] or 'recommend_papers' not in citations[1]['retrieved_by']:
        raise ValueError('Search and personalized recommendation sources required')
    return {'status':'passed','actual_tools':5,'distinct_v1_abstracts_read':2,'llm_calls':0,
        'personalized_training_profile':True,'exact_abstract_quotes':True,'semantic_relevance_evaluated':False}


def render(payload: dict) -> str:
    raw=payload['run'];task=payload['task']
    lines=['# 完整演示：固定流程论文发现','',
        '本地历史回放示例，含训练用户派生结果，仅留data/。不是新质量评测或延迟基准。','',
        fenced('user_id='+task['user_id']+'\nas_of='+task['at']+'\nquery='+task['query']),
        '',f"演示验收：{payload['validation'].get('status')}；LLM调用0；默认推荐content。",'']
    for event in raw['trace']['trace']:
        lines += [f"## {event['attempt']}. {event['tool']}",'',fenced(json.dumps(event['arguments'],ensure_ascii=False)),'']
        result=event['result']
        if 'error' in result:lines += [fenced(json.dumps(result,ensure_ascii=False))]
        elif 'papers' in result:
            lines += [fenced(json.dumps(p,ensure_ascii=False)) for p in result['papers']]
        elif event['tool']=='read_paper':
            lines += [fenced(result['title']),fenced(result['abstract']),fenced(result['source_url'])]
        elif event['tool']=='finalize':lines += [fenced(result.get('answer',str(result)))]
    lines += ['', '完整请求、返回、调用耗时和来源在同目录result.json。原摘要来源可追溯不等于语义相关性或论文结论核验。','']
    return '\n'.join(lines)


def main() -> None:
    parser=argparse.ArgumentParser();parser.add_argument('--query');args=parser.parse_args()
    code,health=request('GET','/health')
    if code!=200 or health['candidates']!=10000 or health['default_recommendation']!='content':raise ValueError('Original unified service required')
    task,selection=select_task(args.query)
    ROOT.mkdir(parents=True,exist_ok=True);folder=Path(tempfile.mkdtemp(prefix='run-',dir=ROOT.resolve()))
    raw=run(task,'fixed');validation={}
    try:validation=validate_run(raw)
    except (ValueError,KeyError,TypeError) as error:validation={'status':'failed','error':str(error)}
    payload={'task':task,'selection':selection,'service':health,'run':raw,'validation':validation,
        'scope':'fixed presentation only; no new metrics, future-feedback selection or LLM dispatch'}
    save(folder/'result.json',payload)
    (folder/'DEMO.md').write_text(render(payload),encoding='utf-8')
    print(json.dumps({'status':validation['status'],'private_demo':str(folder/'DEMO.md'),
        'private_trace':str(folder/'result.json'),'llm_calls':0},ensure_ascii=False),flush=True)
    if validation['status']!='passed':raise SystemExit(1)


if __name__=='__main__':main()
