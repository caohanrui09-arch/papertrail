"""Compare exact legacy/accelerated outputs on fixed-index real events."""
import json
from pathlib import Path
import time

from gsearch.quality_protocol import digest,save
from gsearch.sid_scoring import accelerated_evaluate
from gsearch.supervision import json_rows
from gsearch.supervision_evaluation import evaluate


def main() -> None:
    root=Path('reports/stage45');output=root/'real-scoring-equivalence.json'
    if output.exists():raise FileExistsError('Preserve equivalence evidence')
    data=Path('data/stage44-supervision');all_labels=list(json_rows(data/'tuning.labels.jsonl'))
    # Fixed positional sampling across the full stream; no choice by grades/hits.
    indices=list(range(0,len(all_labels),max(1,len(all_labels)//512)))[:512]
    labels=[all_labels[i] for i in indices];wanted={r['qid'] for r in labels}
    profiles={r['user_key']:r for r in json_rows(data/'profiles.jsonl')}
    catalog={r['doc_id']:r for r in json.loads((data/'catalog.json').read_text())}
    popularity=json.loads((data/'popularity.json').read_text())['counts']
    sources=[Path('data/stage45-sft')/(m+'.tuning.predictions.jsonl') for m in ['popular','content','sar']]
    sources+=sorted(Path('runs/stage45').glob('*/tuning.predictions.jsonl'))
    checks=[]
    for path in sources:
        predictions=[r for r in json_rows(path) if r['qid'] in wanted]
        clock=time.perf_counter();native=evaluate(labels,predictions,profiles,catalog,10,popularity)
        native_seconds=time.perf_counter()-clock
        fast=accelerated_evaluate(labels,predictions,profiles,catalog,10,popularity)
        assert native==fast
        checks.append({'prediction_sha256':digest(path),'events':len(labels),'exact_all_fields_equal':True,
                       'original_scorer_seconds':native_seconds})
    save(output,{'status':'passed','sampling':'fixed every floor(46352/512)th event, first512, independent of predictions/target grades',
        'comparisons':checks,'user_groups':sorted({r['user_group'] for r in labels}),
        'main_metrics_still_all_46352_events':True,'no_training_or_selection_changes':True})
    print({'real_equivalence':'passed','comparisons':len(checks),'events_each':512},flush=True)


if __name__=='__main__':main()
