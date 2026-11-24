"""Same frozen scorer contract, with per-profile validation and full native metrics."""
import argparse
import json
from pathlib import Path
import time

from gsearch.quality_protocol import digest,save
from gsearch.sid_scoring import accelerated_evaluate
from gsearch.supervision import json_rows
from gsearch.supervision_evaluation import locked_run
import scripts.score_sid_sft as driver

REPORT=Path('reports/stage45')
STATE={}


def setup() -> None:
    print({'scorer':'start_original_contract_verification'},flush=True)
    lock=json.loads((REPORT/'run-lock.json').read_text())
    locked_run(lock,digest(Path('reports/stage44/protocol.json')),
               digest(Path('data/stage44-supervision/catalog.json')),
               digest(Path('reports/stage44/evaluation-addendum.json')))
    files={}
    for source in ['reports/stage44/evaluation-lock.json','data/stage44-supervision/build-receipt.json']:
        for name,expected in json.loads(Path(source).read_text())['files'].items():
            assert digest(Path(name))==expected,name
            files[name]=expected
    assert lock['evaluation_lock_sha256']==digest(Path('reports/stage44/evaluation-lock.json'))
    for name in ['gsearch/sid_scoring.py','scripts/score_sid_sft_fast.py','tests/test_sid_scoring.py',
                 'reports/stage45/scoring-addendum.json']:
        files[name]=digest(Path(name))
    path=REPORT/'scoring-lock.json'
    value={'frozen_before_accelerated_scoring':True,'run_lock_sha256':digest(REPORT/'run-lock.json'),
           'files':files,'rules_changed':False,'metrics_source':'unchanged gsearch.supervision.score_rows'}
    if path.exists():assert json.loads(path.read_text())==value
    else:save(path,value)
    print({'scorer':'load_full_inputs_once'},flush=True)
    data=Path('data/stage44-supervision')
    STATE.update(labels=list(json_rows(data/'tuning.labels.jsonl')),
                 profiles={r['user_key']:r for r in json_rows(data/'profiles.jsonl')},
                 catalog={r['doc_id']:r for r in json.loads((data/'catalog.json').read_text())},
                 popularity=json.loads((data/'popularity.json').read_text())['counts'])


def score_cli() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument('--split',choices=['tuning'],required=True)
    parser.add_argument('--predictions',type=Path,required=True)
    parser.add_argument('--run-lock',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    assert args.run_lock==REPORT/'run-lock.json'
    predictions=list(json_rows(args.predictions));start=time.perf_counter()
    print({'scorer':'validate_and_score','output':str(args.output)},flush=True)
    result=accelerated_evaluate(STATE['labels'],predictions,STATE['profiles'],STATE['catalog'],10,STATE['popularity'])
    if args.output.exists():
        original=json.loads(args.output.read_text())
        assert all(original[key]==value for key,value in result.items())
        print({'native_full_comparison_exactly_equal':str(args.output)},flush=True)
        return
    result.update(split='tuning',run_lock_sha256=digest(args.run_lock),predictions_sha256=digest(args.predictions),
        protocol_sha256=digest(Path('reports/stage44/protocol.json')),
        evaluation_addendum_sha256=digest(Path('reports/stage44/evaluation-addendum.json')),
        evaluation_status='previously_used_data; descriptive dev, not a fresh independent test',
        scoring_lock_sha256=digest(REPORT/'scoring-lock.json'),scoring_seconds=time.perf_counter()-start,
        original_metric_source_sha256=digest(Path('gsearch/supervision.py')))
    save(args.output,result)
    print({'score':str(args.output),'user_macro':result['user_macro'],'seconds':result['scoring_seconds']},flush=True)


def main() -> None:
    setup()
    # Dependency injection only for operational validation; driver retains all nine
    # predeclared arms/seeds, output paths, summaries and paired comparisons.
    driver.score=score_cli
    driver.main()


if __name__=='__main__':main()
