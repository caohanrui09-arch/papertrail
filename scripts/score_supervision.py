"""Strict future scorer: data/run locks, complete events and frozen-profile consistency."""
import argparse
import json
from pathlib import Path

from gsearch.quality_protocol import digest, save
from gsearch.supervision import json_rows
from gsearch.supervision_evaluation import evaluate, locked_run


def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument('--split',choices=['tuning','dev_descriptive'],required=True)
    ap.add_argument('--predictions',type=Path,required=True)
    ap.add_argument('--run-lock',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    if args.output.exists():
        raise FileExistsError('Preserve prior evaluations')
    root=Path('reports/stage44');data=Path('data/stage44-supervision')
    protocol=json.loads((root/'protocol.json').read_text(encoding='utf-8'))
    run=json.loads(args.run_lock.read_text(encoding='utf-8'))
    locked_run(run,digest(root/'protocol.json'),protocol['catalog']['sha256'],digest(root/'evaluation-addendum.json'))
    evaluation_lock=json.loads((root/'evaluation-lock.json').read_text(encoding='utf-8'))
    if run.get('evaluation_lock_sha256')!=digest(root/'evaluation-lock.json'):
        raise ValueError('Final evaluation lock not referenced by run manifest')
    for name,expected in evaluation_lock['files'].items():
        if digest(Path(name))!=expected:raise ValueError('Evaluation contract changed: '+name)
    receipt=json.loads((data/'build-receipt.json').read_text(encoding='utf-8'))
    for path,expected in receipt['files'].items():
        if digest(Path(path))!=expected:
            raise ValueError('Frozen supervision changed: '+path)
    if args.split=='dev_descriptive' and not run.get('selected_checkpoint_lock_sha256'):
        raise ValueError('Freeze tuning selection/checkpoint before descriptive dev')
    profiles={r['user_key']:r for r in json_rows(data/'profiles.jsonl')}
    catalog={r['doc_id']:r for r in json.loads((data/'catalog.json').read_text(encoding='utf-8'))}
    labels=list(json_rows(data/(args.split+'.labels.jsonl')))
    popularity=json.loads((data/'popularity.json').read_text(encoding='utf-8'))['counts']
    result=evaluate(labels,list(json_rows(args.predictions)),profiles,catalog,k=10,popularity=popularity)
    result.update(split=args.split,run_lock_sha256=digest(args.run_lock),predictions_sha256=digest(args.predictions),
                  protocol_sha256=digest(root/'protocol.json'),evaluation_addendum_sha256=digest(root/'evaluation-addendum.json'),
                  evaluation_status='previously_used_data; descriptive dev, not a fresh independent test')
    save(args.output,result)
    print({k:v for k,v in result.items() if k not in ['groups']})


if __name__=='__main__':
    main()
