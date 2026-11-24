"""Read-only report CLI, with explicit separate import for model-assisted judgments."""
import argparse
import json

from research73.common import ROOT,DATA,read,write,digest,verify_protocol


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--owner',default='unannotated-report');parser.add_argument('--auxiliary-json');parser.add_argument('--native-export');args=parser.parse_args()
    verify_protocol()
    lock=DATA/'labeling-lock.json'
    if lock.exists():
        for name,h in read(lock)['files'].items():
            if digest(ROOT/name)!=h:raise ValueError('Pre-human evaluation adapter changed; create a new version')
    if args.auxiliary_json:
        items=read(__import__('pathlib').Path(args.auxiliary_json));mapping=read(DATA/'private/pool-map.json')
        allowed={(v['query_id'],v['doc_id']) for v in mapping.values()}
        if not isinstance(items,list):raise ValueError('Model-assistance import must be a list')
        for row in items:
            if row.get('origin')!='model' or (row.get('query_id'),row.get('doc_id')) not in allowed or type(row.get('grade')) is not int or row['grade'] not in (0,1,2) or not row.get('model_name') or not row.get('rationale'):
                raise ValueError('Explicit model origin, model identifier, rationale and pooled IDs required; never imports human labels')
        write(DATA/'auxiliary/model-judgments.json',items)
    from research73.annotations import EvaluationPool,EvaluationStore,ExportStore
    from research73.metrics import algorithm_report
    from research73.agent_report import report
    store=ExportStore(__import__('pathlib').Path(args.native_export),EvaluationPool()) if args.native_export else EvaluationStore(DATA/'work/annotations.sqlite3',EvaluationPool())
    value={'scope':'frozen stage73 descriptive evaluation','algorithm':algorithm_report(store,args.owner),'agent':report()}
    write(ROOT/'reports/stage73/evaluation.json',value);print(json.dumps({'human_labels':value['algorithm']['human_submitted_pairs'],'quality_scores':value['algorithm']['quality_scores'],'agent_finished':value['agent']['finished'],'agent_methods':value['agent']['methods']},ensure_ascii=False))


if __name__=='__main__':main()
