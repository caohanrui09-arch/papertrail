"""Human-gated pooled evaluation using native sklearn and unchanged BEIR MRR."""
import argparse
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import statistics

from .quality_protocol import (digest, save, read_csv, write_csv, judgments, confirmations,
    coverage, import_label_studio, JUDGMENT_FIELDS)

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT/'data/stage20-quality'


def verify_pool(root: Path) -> dict:
    manifest = json.loads((root/'pool-manifest.json').read_text(encoding='utf-8'))
    for name,value in manifest['immutable_assets'].items():
        path=(root/name).resolve()
        if not path.is_relative_to(root.resolve()) or digest(path)!=value:
            raise ValueError('Immutable annotation pool changed: '+name)
    return manifest


def sheet_rows(rows: list[dict], template: list[dict]) -> list[dict]:
    original={r['annotation_id']:r for r in template}
    output=[]
    for row in rows:
        ident=row.get('annotation_id')
        if ident not in original: raise ValueError('Unknown sheet annotation ID')
        if set(row)==set(JUDGMENT_FIELDS):
            output.append(row);continue
        if set(row)!=set(original[ident]): raise ValueError('Unexpected annotation sheet columns')
        for key,value in original[ident].items():
            if key not in JUDGMENT_FIELDS and row[key]!=value:
                raise ValueError('Immutable blind context changed: '+key)
        output.append({key:row[key] for key in JUDGMENT_FIELDS})
    return output


def load_state(root: Path=ROOT, judgments_path: Path|None=None) -> tuple:
    verify_pool(root)
    queries=json.loads((root/'inputs/queries.json').read_text(encoding='utf-8'))
    mapping=json.loads((root/'evaluator/pool-map.json').read_text(encoding='utf-8'))
    runs=json.loads((root/'runs/top10.json').read_text(encoding='utf-8'))
    template=read_csv(root/'blind/candidates.csv')
    path=judgments_path or root/'work/annotations.csv'
    labels=judgments(sheet_rows(read_csv(path),template),mapping)
    confirmed=confirmations(read_csv(root/'work/query-review.csv'),queries)
    return queries,mapping,runs,labels,confirmed


def metric_engine() -> tuple:
    import sklearn.metrics._ranking as ranking
    source=Path(inspect.getfile(ranking)).read_bytes().replace(b'\r\n',b'\n')
    blob=lambda b:hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
    if blob(source)!='0c112537d184113513358ffdf9a33c450e16bea0':
        raise ValueError('Pinned native sklearn ranking source differs')
    path=PROJECT/'third_party/beir_metrics_upstream/custom_metrics.py'
    if blob(path.read_bytes())!='097828c23f4f36a1e20a1c79b7e61188085082d6':
        raise ValueError('Unchanged BEIR source blob differs')
    spec=importlib.util.spec_from_file_location('pinned_beir_custom_metrics',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return ranking.ndcg_score,module.mrr


def native_scores(qrels: dict, rankings: dict) -> dict:
    """Representation adapter only; both metrics are original upstream calls."""
    ndcg_score,mrr=metric_engine()
    values={}
    for qid, grades in qrels.items():
        ids=rankings[qid]
        if len(ids)>10 or len(ids)!=len(set(ids)) or not set(ids).issubset(grades):
            raise ValueError('Unknown or repeated ranked documents')
        documents=sorted(grades)
        if any(type(v) is not int or v not in (0,1,2) for v in grades.values()):
            raise ValueError('Validated graded judgments required')
        # Unreturned judged documents must not fill missing top10 slots. Native
        # sklearn sees their gains for IDCG, but ten zero-gain dummies outrank
        # all unreturned documents for actual DCG.
        gains=[2**grades[d]-1 for d in documents]+[0]*10
        positions={doc:i for i,doc in enumerate(ids)}
        scores=[1000-positions[d] if d in positions else -1-i for i,d in enumerate(documents)]
        scores += [500-i for i in range(10)]
        values[qid]=float(ndcg_score([gains],[scores],k=10,ignore_ties=True))
    ordinal={qid:{doc:float(10-i) for i,doc in enumerate(rankings[qid])} for qid in qrels}
    return {'pooled_ndcg_at10':statistics.mean(values.values()),
        'pooled_mrr_at10':mrr(qrels,ordinal,[10])['MRR@10'],
        'queries':len(qrels),'pooled_queries_with_no_positive_judgment':sum(not any(v>0 for v in gs.values()) for gs in qrels.values()),
        'ndcg_per_query':values,'full_catalog_recall':None}


def evaluate(queries: list[dict], mapping: dict, runs: dict, labels: dict, confirmed: set[str], split: str) -> dict:
    selected=[q for q in queries if q['split']==split]
    qids={q['query_id'] for q in selected}
    pool={key:value for key,value in mapping.items() if value['query_id'] in qids}
    if not selected or not qids.issubset(confirmed) or any(key not in labels for key in pool):
        raise ValueError('Awaiting complete HUMAN judgments and confirmed queries; no quality score produced')
    qrels={qid:{} for qid in qids}
    for ident,item in pool.items():
        label=labels[ident]
        if label.get('judgment_origin')!='human': raise ValueError('Human judgment origin required')
        qrels[item['query_id']][item['doc_id']]=label['grade']
    results={method:native_scores(qrels,{qid:result[qid] for qid in qids}) for method,result in runs.items()}
    return {'split':split,'methods':results,'judgments':'complete current candidate pool, explicitly declared human',
        'scope':'draft queries confirmed by humans; not human-authored originals or full-catalog recall',
        'semantic_agent_selection_scored':False}


def configuration(root: Path=ROOT) -> dict:
    manifest=verify_pool(root)
    lock=PROJECT/'reports/stage20/locked-before-judgments.json'
    value=json.loads(lock.read_text())
    for name,expected in value['code'].items():
        if digest(PROJECT/name)!=expected: raise ValueError('Pre-judgment code changed')
    for name,expected in value['protocol'].items():
        if digest(PROJECT/name)!=expected: raise ValueError('Pre-judgment protocol changed')
    if value['pool_manifest_sha256']!=digest(root/'pool-manifest.json'):
        raise ValueError('Candidate pool version changed')
    return {'code':value['code'],'protocol':value['protocol'],'pool_manifest_sha256':value['pool_manifest_sha256']}


def tuning_labels_hash(queries: list[dict], mapping: dict, labels: dict) -> str:
    qids={q['query_id'] for q in queries if q['split']=='tuning'}
    selected={ident:labels[ident] for ident,item in mapping.items() if item['query_id'] in qids and ident in labels}
    return hashlib.sha256(json.dumps(selected,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('status','score','freeze','import-label-studio'))
    parser.add_argument('--split',choices=('tuning','evaluation'),default='tuning')
    parser.add_argument('--input',type=Path);parser.add_argument('--output',type=Path)
    parser.add_argument('--annotator-id',default='');parser.add_argument('--attest-human',action='store_true')
    args=parser.parse_args()
    if args.action=='import-label-studio':
        configuration()
        if args.input is None or args.output is None: raise ValueError('Explicit input and new output required')
        output=args.output.resolve()
        if not output.is_relative_to((ROOT/'work').resolve()) or output.exists():
            raise ValueError('New private work/ output required; no existing annotations overwritten')
        mapping=json.loads((ROOT/'evaluator/pool-map.json').read_text())
        rows=import_label_studio(json.loads(args.input.read_text(encoding='utf-8')),mapping,args.annotator_id,args.attest_human)
        write_csv(output,JUDGMENT_FIELDS,rows)
        print(json.dumps({'imported_declared_human_rows':len(rows),'identity_authentication_performed':False}));return
    configuration()
    queries,mapping,runs,labels,confirmed=load_state(judgments_path=args.input)
    if args.action=='status':
        print(json.dumps(coverage(queries,mapping,runs,labels,confirmed),ensure_ascii=False,indent=2));return
    config=configuration()
    destination=ROOT/'human-results'
    if args.action=='freeze':
        # Only process successfully scored tuning; no automatic weight search.
        path=destination/'tuning.json'
        recorded=json.loads(path.read_text(encoding='utf-8'))
        current=evaluate(queries,mapping,runs,labels,confirmed,'tuning')
        if recorded['quality']!=current or recorded['configuration']!=config:
            raise ValueError('Tuning inputs or configuration differ from scored version')
        lock=destination/'selection-lock.json'
        if lock.exists(): raise ValueError('Human-evaluation selection already frozen')
        save(lock,{'tuning_result_sha256':digest(path),'tuning_labels_sha256':tuning_labels_hash(queries,mapping,labels),
            'configuration':config,'selection':'predeclared .7 query/.3 same displayed context; no automatic tuning search'})
        print(json.dumps({'human_evaluation_unlocked':True}));return
    if args.split=='evaluation':
        frozen=json.loads((destination/'selection-lock.json').read_text())
        if frozen['configuration']!=config or frozen['tuning_labels_sha256']!=tuning_labels_hash(queries,mapping,labels) or frozen['tuning_result_sha256']!=digest(destination/'tuning.json'):
            raise ValueError('Frozen tuning/selection drift')
    quality=evaluate(queries,mapping,runs,labels,confirmed,args.split)
    output=destination/(args.split+'.json')
    if output.exists(): raise ValueError('Do not overwrite human-evaluation results')
    save(output,{'quality':quality,'configuration':config,'input_judgments_sha256':digest(args.input or ROOT/'work/annotations.csv')})
    print(json.dumps(quality,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
