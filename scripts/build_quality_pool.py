"""Prepare a label-free native retrieval pool in the independent CPU runtime."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT/'data/stage20-quality'
REPORT = PROJECT/'reports/stage20'


def worker() -> None:
    # -c launcher starts in the existing replica. Never import legacy numerical
    # modules before its audited sklearn target has been selected.
    sys.path.insert(0, str(Path('.cache/stage11/deps').resolve()))
    from gsearch.local_service import load_model
    from gsearch.quality_retrieval import QualityRetrieval, METHODS
    from gsearch.quality_protocol import digest, save, write_csv, csv_text, JUDGMENT_FIELDS
    from threadpoolctl import threadpool_limits
    import hashlib
    import statistics
    queries = json.loads((ROOT/'inputs/queries.json').read_text(encoding='utf-8'))
    profiles = json.loads((ROOT/'evaluator/profiles-private.json').read_text(encoding='utf-8'))
    if (ROOT/'runs').exists(): raise ValueError('Pool run already exists; preserve previous attempt')
    (ROOT/'runs').mkdir()
    started = time.perf_counter()
    with threadpool_limits(limits=1):
        model = load_model()
        retriever = QualityRetrieval(model, profiles)
        fit_seconds = time.perf_counter()-started
        runs = {method:{} for method in METHODS}
        responses, timings = [], []
        for index, query in enumerate(queries):
            profile = profiles[query['profile_id']]
            for round_number in range(3):
                order = (index+round_number)%3
                methods = METHODS[order:]+METHODS[:order]
                for method in methods:
                    before = time.perf_counter()
                    response = retriever.search(query, profile, method)
                    elapsed = time.perf_counter()-before
                    ids = [r['doc_id'] for r in response['papers']]
                    if len(ids) != len(set(ids)) or len(ids)>10:
                        raise ValueError('Ambiguous top10')
                    eligible = set(model.catalog[int(i)] for i in model.eligible(profile['user_id'],query['at']))
                    if not set(ids).issubset(eligible):
                        raise ValueError('Unknown, future or seen result')
                    if round_number and ids != runs[method][query['query_id']]:
                        raise ValueError('Repeated native ranking changed')
                    runs[method][query['query_id']] = ids
                    timings.append({'query_id':query['query_id'],'method':method,'round':round_number,
                        'seconds':elapsed,'snapshot_cache_hit':response.get('index',{}).get('snapshot_cache_hit'),
                        'snapshot_seconds':response.get('index',{}).get('snapshot_seconds',0.)})
                    if round_number == 0:
                        responses.append({'query_id':query['query_id'],'method':method,'response':response})
            print(json.dumps({'queries_processed':index+1,'queries_total':len(queries)}),flush=True)
        save(ROOT/'runs/top10.json',runs)
        save(ROOT/'runs/raw-first-round.json',responses)
        save(ROOT/'runs/latency.json',timings)
        unique = set(d for results in runs.values() for ids in results.values() for d in ids)
        unique.update(d for p in profiles.values() for d in p['history_doc_ids'])
        originals = {}
        for doc in sorted(unique):
            original = model.read(doc,queries[0]['at'])
            if original.get('source_verified') is not True or original['version'] != 1:
                raise ValueError('Official original v1 verification failed')
            originals[doc] = original
        save(ROOT/'evaluator/verified-originals.json',originals)
        by_query = {q['query_id']:q for q in queries}
        mapping, blinded, studio = {}, [], []
        fields = ['annotation_id','query_id','query_origin','intent','request','profile_context','title','abstract','version','source_url',
            'grade','annotator_id','judgment_origin','judged_at','rationale']
        query_order = sorted(by_query, key=lambda q:hashlib.sha256(('blind-query:'+q).encode()).hexdigest())
        for qid in query_order:
            query = by_query[qid]
            context = profiles[query['profile_id']]
            context_text = '\n\n'.join(f"{originals[d]['title']}\n{originals[d]['abstract']}\n{originals[d]['source_url']}" for d in context['history_doc_ids'])
            pool = set(d for results in runs.values() for d in results[qid])
            pool = sorted(pool,key=lambda d:hashlib.sha256(('blind-paper:'+qid+':'+d).encode()).hexdigest())
            for doc in pool:
                ident = 'a20-'+hashlib.sha256((qid+':'+doc).encode()).hexdigest()[:24]
                if ident in mapping: raise ValueError('Blind identifier collision')
                original = originals[doc]
                mapping[ident] = {'query_id':qid,'doc_id':doc,'split':query['split'],
                    'sources':{m:runs[m][qid].index(doc)+1 for m in METHODS if doc in runs[m][qid]}}
                data = {'annotation_id':ident,'query_id':qid,'query_origin':'assistant_draft','intent':query['intent'],
                    'request':query['request'],'profile_context':context_text,'title':original['title'],
                    'abstract':original['abstract'],'version':'1','source_url':original['source_url']}
                blinded.append({**{k:csv_text(v) for k,v in data.items()},
                    **{k:'' for k in JUDGMENT_FIELDS if k!='annotation_id'}})
                studio.append({'data':data})
        write_csv(ROOT/'blind/candidates.csv',fields,blinded)
        write_csv(ROOT/'work/annotations.csv',fields,blinded)
        save(ROOT/'blind/label-studio-tasks.json',studio)
        save(ROOT/'evaluator/pool-map.json',mapping)
        source_contexts = {key:{'origin':p['origin'],'papers':[originals[d] for d in p['history_doc_ids']]} for key,p in profiles.items()}
        save(ROOT/'blind/history-contexts.json',source_contexts)
        shutil.copy2(PROJECT/'docs/label_studio_relevance.xml',ROOT/'blind/label-config.xml')
        costs = {}
        for method in METHODS:
            values = sorted(t['seconds'] for t in timings if t['method']==method)
            warm = sorted(t['seconds'] for t in timings if t['method']==method and t['snapshot_cache_hit'] is not False)
            costs[method] = {'requests':len(values),'mean_ms':1000*statistics.mean(values),
                'p95_ms_nearest_rank':1000*values[__import__('math').ceil(.95*len(values))-1],
                'warm_mean_ms':1000*statistics.mean(warm) if warm else None,
                'returned_top10_total':sum(len(ids) for ids in runs[method].values())}
        save(REPORT/'retrieval-cost.json',{'methods':costs,'rounds':3,'one_time_model_and_adapter_fit_seconds':fit_seconds,
            'source_verified_unique_documents_including_histories':len(originals),
            'pooled_pairs':len(mapping),'human_labels':0,'quality_scores_computed':False,
            'scope':'offline single CPU-process timing, not serving QPS; no query/result-score caches',
            'bm25_snapshot_builds':[t for t in timings if t['snapshot_cache_hit'] is False]})
        files = [p for directory in ('inputs','evaluator','runs','blind','templates') for p in (ROOT/directory).rglob('*') if p.is_file()]
        save(ROOT/'pool-manifest.json',{'immutable_assets':{str(p.relative_to(ROOT)):digest(p) for p in files},
            'mutable_work_excluded':True,'human_labels_at_preparation':0,'queries_have_only_assistant_draft_origin':True})
        print(json.dumps({'pool_prepared':True,'pooled_pairs':len(mapping),'human_judgments':0}),flush=True)


def main() -> None:
    parser=argparse.ArgumentParser();parser.add_argument('--worker',action='store_true');args=parser.parse_args()
    if args.worker:
        worker();return
    from scripts.manage_stage17_env import BASE,VENV,environment
    from gsearch.quality_protocol import digest,save
    if (ROOT/'runs').exists():raise ValueError('Existing pool outputs must be preserved')
    overlay={}
    for name in ('gsearch/quality_retrieval.py','gsearch/quality_protocol.py'):
        target=BASE/'replica'/name
        if target.exists() and target.read_bytes()!=(PROJECT/name).read_bytes():
            raise ValueError('An existing overlay differs; version it explicitly')
        shutil.copy2(PROJECT/name,target);overlay[name]=digest(PROJECT/name)
    save(PROJECT/'.cache/stage20/overlay.json',overlay)
    launcher="import runpy,sys;sys.argv=[sys.argv[1],'--worker'];runpy.run_path(sys.argv[0],run_name='__main__')"
    subprocess.run([str(VENV/'Scripts/python.exe'),'-E','-s','-u','-c',launcher,str(Path(__file__).resolve())],
        cwd=BASE/'replica',env=environment(),check=True)


if __name__=='__main__':main()
