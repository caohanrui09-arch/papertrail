"""Freeze operational scorer/fallback and an intentionally unfilled training template."""
from collections import Counter,defaultdict
import json
from pathlib import Path

from gsearch.quality_protocol import save,digest
from gsearch.supervision import json_rows

ROOT=Path('reports/stage44')
DATA=Path('data/stage44-supervision')


def main() -> None:
    if (ROOT/'evaluation-lock.json').exists():raise FileExistsError('Evaluation already locked')
    counts=Counter()
    for row in json_rows(DATA/'train.feedback.jsonl'):
        if row['rating']==1 and row['available_at_event']:counts[row['doc_id']]+=1
    catalog=json.loads((DATA/'catalog.json').read_text(encoding='utf-8'))
    save(DATA/'popularity.json',{'counts':{r['doc_id']:counts[r['doc_id']] for r in catalog},
        'source_sha256':digest(DATA/'train.feedback.jsonl'),'tie_break':'canonical doc ID',
        'source':'eligible pre-cutoff training positives only; common fallback, not a fitted neural model'})
    files=[ROOT/'protocol.json',ROOT/'evaluation-addendum.json',DATA/'build-receipt.json',DATA/'popularity.json',
           Path('gsearch/supervision.py'),Path('gsearch/supervision_evaluation.py'),Path('gsearch/evaluate.py'),Path('scripts/score_supervision.py')]
    save(ROOT/'evaluation-lock.json',{'status':'frozen_before_training_and_quality_predictions','files':{str(p):digest(p) for p in files},
        'training_run_frozen':False,'real_quality_results':False})
    template={k:None for k in ['base_model_revision','base_weights_sha256','tokenizer_sha256','content_mapping_sha256',
        'shuffled_mapping_sha256','optimizer_updates','effective_batch','seed_schedule','input_target_token_id_contract',
        'precision','optimizer','learning_rate','checkpoint_steps']}
    template.update(template_only=True,protocol_sha256=digest(ROOT/'protocol.json'),catalog_sha256=digest(DATA/'catalog.json'),
        evaluation_addendum_sha256=digest(ROOT/'evaluation-addendum.json'),evaluation_lock_sha256=digest(ROOT/'evaluation-lock.json'),
        ordered_training_sample_ids_sha256=digest(DATA/'train.next_item.jsonl'),beam_size=10,
        resource_preflight_passed=False,real_tokenizer_and_decode_preflight_passed=False,frozen_before_training=False,
        instruction='Copy into a new run directory and fill actual immutable configuration/preflight receipts before training; this template is intentionally rejected.')
    # The ordered training artifact hash identifies the saved canonical sample order;
    # a future shuffled loader must additionally lock its exact permutation.
    template['ordered_training_sample_ids_sha256']=None
    save(ROOT/'run-lock.template.json',template)
    save(ROOT/'readiness.json',{'supervision_prepared':True,'evaluation_contract_frozen':True,'training_run_frozen':False,
        'sft_started':False,'rl_started':False,'fresh_independent_test':False,
        'next_gates':['exact paired training manifest and data-order hashes','resource smoke test','real tokenizer/SID/EOS and constrained-decoder validation'],
        'evaluation_lock_sha256':digest(ROOT/'evaluation-lock.json')})
    print({'evaluation_lock':digest(ROOT/'evaluation-lock.json'),'eligible_popularity_events':sum(counts.values()),'training_started':False})


if __name__=='__main__':main()
