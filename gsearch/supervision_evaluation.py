"""Operational evaluation checks layered on the frozen supervision metrics."""
import math
import re

from .supervision import require_run_lock, score_rows


def locked_run(lock: dict, protocol_sha: str, catalog_sha: str, addendum_sha: str) -> None:
    require_run_lock(lock,protocol_sha,catalog_sha)
    if lock.get('evaluation_addendum_sha256')!=addendum_sha:
        raise ValueError('Evaluation addendum not locked')
    for key in ['base_weights_sha256','tokenizer_sha256','content_mapping_sha256','shuffled_mapping_sha256','ordered_training_sample_ids_sha256']:
        if not isinstance(lock[key],str) or not re.fullmatch('[0-9a-f]{64}',lock[key]):
            raise ValueError('Exact SHA256 required: '+key)
    if not isinstance(lock['base_model_revision'],str) or not re.fullmatch('[0-9a-f]{40}',lock['base_model_revision']):
        raise ValueError('Immutable model revision required')
    for key in ['optimizer_updates','effective_batch']:
        if type(lock[key]) is not int or lock[key]<1:
            raise ValueError('Positive integer budget required: '+key)
    if not isinstance(lock['seed_schedule'],list) or len(lock['seed_schedule'])<3 or any(type(s) is not int for s in lock['seed_schedule']) or len(set(lock['seed_schedule']))!=len(lock['seed_schedule']):
        raise ValueError('At least three distinct integer seeds must be frozen')
    if not isinstance(lock['checkpoint_steps'],list) or not lock['checkpoint_steps'] or any(type(s) is not int or s<1 or s>lock['optimizer_updates'] for s in lock['checkpoint_steps']) or lock['checkpoint_steps']!=sorted(set(lock['checkpoint_steps'])):
        raise ValueError('Checkpoint steps must be distinct, ordered and within budget')
    if lock['precision'] not in ['bf16','fp16','fp32'] or not isinstance(lock['optimizer'],dict) or not lock['optimizer']:
        raise ValueError('Precision and concrete optimizer settings required')
    if isinstance(lock['learning_rate'],bool) or not isinstance(lock['learning_rate'],(int,float)) or not math.isfinite(lock['learning_rate']) or lock['learning_rate']<=0:
        raise ValueError('Positive finite learning rate required')
    contract=lock['input_target_token_id_contract']
    if not isinstance(contract,dict) or contract.get('labels')!='token_ids' or contract.get('prompt_loss_mask')!=-100 or contract.get('eos_required') is not True:
        raise ValueError('Raw token-ID labels, prompt masking and EOS must be locked')


def evaluate(labels: list[dict], predictions: list[dict], profiles: dict, catalog: dict, k: int=10, popularity: dict | None=None) -> dict:
    label_by_id={r['qid']:r for r in labels}
    per_user={}
    for row in predictions:
        if row.get('qid') not in label_by_id:
            raise ValueError('Unknown evaluation qid')
        user=label_by_id[row['qid']]['user_key']
        if user in per_user and row.get('doc_ids')!=per_user[user]:
            raise ValueError('Fixed profile received different predictions; event ID/time must not reveal targets')
        if popularity is not None and profiles.get(user,{}).get('eligible_train_positive_count',0)==0 and row.get('doc_ids'):
            seen=set(profiles.get(user,{}).get('seen_doc_ids',[]))
            expected=sorted((d for d in catalog if d not in seen),key=lambda d:(-popularity.get(d,0),d))[:k]
            if row['doc_ids']!=expected:
                raise ValueError('Zero-context profile must use the shared frozen popularity fallback')
        per_user[user]=row.get('doc_ids')
    result=score_rows(labels,predictions,profiles,catalog,k)
    result['source_user_event_counts']={
        'new_to_source_training':sum(r['user_key'] not in profiles for r in labels),
        'existing_without_catalog_positive_context':sum(r['user_key'] in profiles and profiles[r['user_key']]['eligible_train_positive_count']==0 for r in labels),
        'existing_with_catalog_context':sum(r['user_key'] in profiles and profiles[r['user_key']]['eligible_train_positive_count']>0 for r in labels)}
    return result
