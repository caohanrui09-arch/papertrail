"""Verify actual blind pool, empty human gates, cost recount and old seals."""
from collections import Counter
import contextlib
import csv
from datetime import datetime
import json
import math
from pathlib import Path
import statistics
import subprocess
import unittest
import xml.etree.ElementTree as ET

from gsearch.quality_protocol import digest,save,read_csv,csv_text,coverage
from gsearch.human_quality import load_state,configuration
from scripts.manage_stage17_env import VENV,environment,BASE

PROJECT=Path(__file__).resolve().parents[1]
ROOT=PROJECT/'data/stage20-quality'
REPORT=PROJECT/'reports/stage20'


def main() -> None:
    output=REPORT/'preparation-validation.json'
    if output.exists():raise ValueError('Do not overwrite verification')
    configuration()
    queries,mapping,runs,labels,confirmed=load_state()
    if labels or confirmed or len(queries)!=24:raise ValueError('Preparation must have24 drafts and0 human labels')
    if any(q['query_origin']!='assistant_draft' or q['human_authored'] for q in queries):
        raise ValueError('Query origin misrepresented')
    if Counter(q['intent'] for q in queries)!=Counter(topic=8,recommend=8,mixed=8):raise ValueError('Intent counts differ')
    profiles=json.loads((ROOT/'evaluator/profiles-private.json').read_text())
    families={split:{q['topic_family'] for q in queries if q['split']==split} for split in ('tuning','evaluation')}
    users={split:{profiles[q['profile_id']]['user_id'] for q in queries if q['split']==split} for split in ('tuning','evaluation')}
    if families['tuning']&families['evaluation'] or users['tuning']&users['evaluation']:
        raise ValueError('Family/user crosses split')
    raw=json.loads((PROJECT/'data/stage13-expansion/documents.json').read_text(encoding='utf-8'))
    by_id={r['doc_id']:r for r in raw}
    all_users=set.union(*users.values());seen={u:set() for u in all_users};likes={u:set() for u in all_users}
    with (PROJECT/'data/stage9-recommendation/train.csv').open(encoding='utf-8',newline='') as stream:
        for row in csv.DictReader(stream):
            user=row['user_id']
            if user in seen:
                seen[user].add(row['arxiv_id'])
                if float(row['rating'])==1:likes[user].add(row['arxiv_id'])
    for profile in profiles.values():
        if len(set(profile['history_doc_ids']))!=5 or not set(profile['history_doc_ids']).issubset(likes[profile['user_id']]):
            raise ValueError('Context is not five genuine training likes')
    for query in queries:
        user=profiles[query['profile_id']]['user_id'];qid=query['query_id']
        union=set()
        for method,results in runs.items():
            ids=results[qid]
            if len(ids)!=len(set(ids)) or len(ids)>10:raise ValueError('Invalid rank list')
            if any(d not in by_id or d in seen[user] or datetime.fromisoformat(by_id[d]['available_at'])>datetime.fromisoformat(query['at']) for d in ids):
                raise ValueError('Seen/future/unknown result')
            union.update(ids)
        mapped={v['doc_id'] for v in mapping.values() if v['query_id']==qid}
        if union!=mapped:raise ValueError('Blind pool is not exact union')
    originals=json.loads((ROOT/'evaluator/verified-originals.json').read_text(encoding='utf-8'))
    from gsearch.metadata_fetch import upstream
    from gsearch.paper_identity import arxiv_identity
    parsed={}
    for doc,original in originals.items():
        source=by_id[doc];path=Path(source['provenance']['raw_path'])
        if str(path) not in parsed:
            if digest(path)!=source['provenance']['raw_sha256']:raise ValueError('Original raw body changed')
            parsed[str(path)]=upstream()._feed.parse(path.read_bytes()).results
        match=[r for r in parsed[str(path)] if arxiv_identity(r.entry_id)==(doc,1)]
        if len(match)!=1 or original['version']!=1 or match[0].summary!=original['abstract'] or match[0].title!=original['title'] or original['source_url']!=source['source_url']:
            raise ValueError('Blind text differs from native originalv1')
    blind=read_csv(ROOT/'blind/candidates.csv')
    tasks=json.loads((ROOT/'blind/label-studio-tasks.json').read_text(encoding='utf-8'))
    if len(blind)!=len(mapping) or len(tasks)!=len(mapping):raise ValueError('Annotation row counts differ')
    forbidden={'method','rank','score','sources','split','user_id','predictions','annotations'}
    expected_ids=set(mapping)
    if {r['annotation_id'] for r in blind}!=expected_ids:raise ValueError('Blind IDs do not match pool')
    queries_by_id={q['query_id']:q for q in queries}
    for row in blind:
        if forbidden&set(row) or any(row[k] for k in ('grade','annotator_id','judgment_origin','judged_at','rationale')):
            raise ValueError('Leaked algorithm metadata or prefilled labels')
        original=originals[mapping[row['annotation_id']]['doc_id']]
        for key in ('title','abstract','source_url'):
            if row[key]!=csv_text(original[key]):raise ValueError('Blind CSV text changed')
        if row['request']!=queries_by_id[row['query_id']]['request']:raise ValueError('Query changed')
    for task in tasks:
        if set(task)!={'data'} or forbidden&set(task['data']):raise ValueError('Label Studio task not blind/data-only')
    config=ET.parse(ROOT/'blind/label-config.xml').getroot()
    if {choice.attrib['value'] for choice in config.findall('.//Choice')}!={'0 不相关','1 部分相关','2 高度相关'}:
        raise ValueError('Label choices differ')
    if config.findall('.//HyperText'):raise ValueError('Raw source HTML not allowed')
    timings=json.loads((ROOT/'runs/latency.json').read_text())
    costs=json.loads((REPORT/'retrieval-cost.json').read_text())
    if len(timings)!=216:raise ValueError('Missing paired timing observations')
    for method,record in costs['methods'].items():
        values=sorted(t['seconds'] for t in timings if t['method']==method)
        if abs(record['mean_ms']-1000*statistics.mean(values))>1e-9 or abs(record['p95_ms_nearest_rank']-1000*values[math.ceil(.95*len(values))-1])>1e-9:
            raise ValueError('Cost recount differs')
    logs=PROJECT/'.cache/stage20';logs.mkdir(parents=True,exist_ok=True)
    for action in ('status','score'):
        command=[str(VENV/'Scripts/python.exe'),'-E','-s','-m','gsearch.human_quality',action]
        if action=='score':command+=['--split','tuning']
        result=subprocess.run(command,cwd=PROJECT,env=environment(),capture_output=True,text=True)
        (logs/(action+'-gate.log')).write_text(result.stdout+result.stderr,encoding='utf-8')
        if action=='status':
            status=json.loads(result.stdout)
            if result.returncode or status['human_judged_pairs'] or status['ndcg_at10'] is not None:
                raise ValueError('Actual status CLI did not remain unjudged')
        elif result.returncode==0 or 'Awaiting complete HUMAN judgments' not in result.stderr or (ROOT/'human-results/tuning.json').exists():
            raise ValueError('Actual scoring CLI failed to block empty judgments')
    with (logs/'regression-tests.log').open('w',encoding='utf-8') as stream,contextlib.redirect_stdout(stream),contextlib.redirect_stderr(stream):
        tests=unittest.TextTestRunner(stream=stream,verbosity=1).run(unittest.defaultTestLoader.discover(str(PROJECT/'tests')))
    if not tests.wasSuccessful():raise ValueError('Regression failed; preserve private log')
    from gsearch.benchmark_cold_fusion import history
    from gsearch.showcase import verify_receipt
    from gsearch.relocated_demo import verify_bundle
    history();history_counts={}
    groups={15:('code','data','outputs','report'),16:('code','materials','outputs','private_data','report'),
        17:('code','docs','outputs','private_replay_assets','report'),18:('code','docs','outputs','report'),
        19:('code','outputs','private_data','docs','report')}
    for n,fields in groups.items():history_counts[str(n)]=verify_receipt(PROJECT/f'reports/stage{n}/final-validation.json',fields)
    bundle=verify_bundle(BASE/'replica')
    process=subprocess.run([str(VENV/'Scripts/python.exe'),'-E','-s','-c',
        "import json,importlib.metadata as m;print(json.dumps({d.metadata['Name']:d.version for d in m.distributions()}))"],
        env=environment(),capture_output=True,text=True,check=True)
    versions=json.loads(process.stdout)
    if versions!=json.loads((PROJECT/'reports/stage17/runtime-versions.json').read_text())['installed_versions']:
        raise ValueError('Independent packages changed')
    result={'status':'preparation_verified_awaiting_human','regression_tests':tests.testsRun,'failures':0,'errors':0,
        'queries':24,'assistant_draft_queries':24,'human_authored_queries':0,'human_confirmed_queries':0,
        'blind_pairs':len(mapping),'human_judgments':0,'quality_scores_computed':False,
        'native_original_v1_documents_reverified':len(originals),'native_raw_bodies_reparsed':len(parsed),
        'timing_observations_recounted':len(timings),'blind_metadata_checked':True,
        'label_studio_schema_static_checked':True,'label_studio_server_installed_or_ui_tested':False,
        'actual_empty_human_score_cli_blocked':True,'stages3_19_unchanged':True,
        'history_checked_assets':history_counts,'original_replica_assets':len(bundle['files']),
        'independent_packages_unchanged':len(versions),'work_files_intentionally_mutable':True}
    save(output,result)
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
