"""Canonical chronological supervision adapters; no model or web dependencies."""
from collections import Counter, defaultdict, deque
from datetime import datetime
from functools import lru_cache
import hashlib
import json
from itertools import groupby
from pathlib import Path

import pandas as pd

from .evaluate import metrics
from .paper_identity import canonical_id


def user_key(raw: str) -> str:
    # Pseudonym for local joins only, not an anonymization guarantee.
    return hashlib.sha256(('scholar-inbox-92b0fac:'+raw).encode()).hexdigest()


@lru_cache(maxsize=400000)
def identity(raw: str) -> str:
    return canonical_id(raw)


def frame(path: Path, split: str, file_sha: str) -> pd.DataFrame:
    data=pd.read_csv(path,dtype={'arxiv_id':str,'user_id':str,'time':str})
    if not data.rating.isin([-1,1]).all() or data[['arxiv_id','user_id','time']].isna().any().any():
        raise ValueError('Invalid rating or missing source field')
    data['source_row']=data.index+2
    data['doc_id']=data.arxiv_id.map(identity)
    data['user_key']=data.user_id.map(user_key)
    data['at']=pd.to_datetime(data.time,format='mixed',utc=True,errors='raise')
    if data.duplicated(['user_key','doc_id']).any():
        raise ValueError('Resolve canonical user-paper duplicate ratings explicitly')
    data['event_id']=[hashlib.sha256(f'{split}:{file_sha}:{i}'.encode()).hexdigest() for i in data.source_row]
    return data


def json_line(stream, value: dict) -> None:
    stream.write(json.dumps(value,ensure_ascii=False,separators=(',',':'))+'\n')


def json_rows(path: Path):
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def build_train(data: pd.DataFrame, catalog: dict, max_items: int, sample_stream, feedback_stream) -> tuple[dict,dict,Counter]:
    """Standard bounded positive prefixes, with strict timestamp batches."""
    available={d:pd.Timestamp(row['available_at']) for d,row in catalog.items()}
    positive_counts=Counter(data.loc[data.rating==1,'doc_id'])
    profiles,counts={},Counter()
    ordered=data.sort_values(['user_key','at','doc_id'],kind='stable')
    for key,user in ordered.groupby('user_key',sort=False):
        history=deque(maxlen=max_items)
        seen=set()
        eligible_total=0
        for at,records in groupby(user.itertuples(index=False),key=lambda row:row.at):
            pending=[]
            for row in records:
                counts['source_events']+=1
                if row.doc_id not in catalog:
                    counts['outside_catalog_events']+=1
                    if row.rating==1:counts['outside_catalog_positives']+=1
                    continue
                eligible=available[row.doc_id]<=at
                json_line(feedback_stream,{'event_id':row.event_id,'user_key':key,'doc_id':row.doc_id,
                    'rating':int(row.rating),'at':at.isoformat(),'source_row':int(row.source_row),
                    'available_at_event':bool(eligible)})
                seen.add(row.doc_id)
                if row.rating!=1:
                    counts['negative_candidate_events']+=1
                    continue
                counts['candidate_positives']+=1
                if not eligible:
                    counts['positive_before_availability_proxy']+=1
                    continue
                if not history:
                    counts['positive_without_strict_past_history']+=1
                else:
                    if not all(pd.Timestamp(h['at'])<at for h in history):
                        raise AssertionError('Target or equal-time event entered history')
                    json_line(sample_stream,{'sample_id':row.event_id,'user_key':key,'target_doc_id':row.doc_id,
                        'target_version_key':catalog[row.doc_id]['version_key'],'target_at':at.isoformat(),
                        'source_row':int(row.source_row),'history_doc_ids':[h['doc_id'] for h in history],
                        'history_ats':[h['at'] for h in history],'history_event_ids':[h['event_id'] for h in history]})
                    counts['supervised_samples']+=1
                pending.append({'doc_id':row.doc_id,'at':at.isoformat(),'event_id':row.event_id})
                eligible_total+=1
            history.extend(pending)
        profiles[key]={'user_key':key,'history_doc_ids':[h['doc_id'] for h in history],
                       'history_ats':[h['at'] for h in history],'history_event_ids':[h['event_id'] for h in history],
                       'eligible_train_positive_count':eligible_total,'seen_doc_ids':sorted(seen),
                       'source_train_events':len(user)}
    return profiles,dict(counts),positive_counts


def user_group(profile: dict) -> str:
    n=profile.get('eligible_train_positive_count',0)
    return 'cold' if n==0 else 'sparse' if n<5 else 'warm'


def evaluation_label(row, profiles: dict, catalog: dict, source_meta: dict, train_likes: Counter) -> dict:
    profile=profiles.get(row.user_key,{'history_doc_ids':[],'seen_doc_ids':[]})
    if row.doc_id not in catalog:
        reason='outside_frozen_catalog'
    elif pd.Timestamp(catalog[row.doc_id]['available_at'])>row.at:
        reason='not_yet_available'
    elif row.doc_id in profile['seen_doc_ids']:
        reason='masked_train_seen'
    else:
        reason=None
    item_group=('no_train_like' if train_likes[row.doc_id]==0 else 'trainliked') if row.doc_id in catalog else 'outside_catalog'
    return {'qid':row.event_id,'user_key':row.user_key,'target_doc_id':row.doc_id,
        'target_version_key':catalog.get(row.doc_id,{}).get('version_key'),'at':row.at.isoformat(),
        'source_row':int(row.source_row),'rankable':reason is None,'miss_reason':reason,
        'user_group':user_group(profile),'item_group':item_group,
        'target_train_positive_count':int(train_likes[row.doc_id]),
        'in_original_10000_corpus':row.doc_id in source_meta,
        'after_training_catalog_cutoff':row.doc_id in source_meta and row.doc_id not in catalog}


def score_rows(labels: list[dict], predictions: list[dict], profiles: dict, catalog: dict, k: int=10) -> dict:
    expected={r['qid']:r for r in labels}
    if len(expected)!=len(labels) or not labels:
        raise ValueError('Nonempty, distinct evaluation labels required')
    submitted={}
    for row in predictions:
        if set(row)!={'qid','doc_ids'} or row['qid'] not in expected or row['qid'] in submitted:
            raise ValueError('Unknown/duplicate qid or unexpected prediction schema')
        if not isinstance(row['doc_ids'],list) or len(row['doc_ids'])>k:
            raise ValueError('Prediction list must contain at most k slots')
        if any(d is not None and not isinstance(d,str) for d in row['doc_ids']):
            raise ValueError('Prediction slots must be canonical strings or None')
        submitted[row['qid']]=row['doc_ids']
    if set(submitted)!=set(expected):
        raise ValueError('Missing prediction rows; submit explicit empty lists for failed requests')
    per_user=defaultdict(list)
    per_group=defaultdict(lambda:defaultdict(list))
    legal_slots=duplicate_slots=unique_slots=0
    for label in labels:
        seen=set(profiles.get(label['user_key'],{}).get('seen_doc_ids',[]))
        clean=[]
        generated=set()
        for doc in submitted[label['qid']]:
            legal=(doc in catalog and doc not in seen and pd.Timestamp(catalog[doc]['available_at'])<=pd.Timestamp(label['at'])) if doc is not None else False
            if legal:
                legal_slots+=1
            duplicate=doc is not None and doc in generated
            if duplicate:duplicate_slots+=1
            if legal and not duplicate:
                unique_slots+=1
                clean.append(doc)
            else:
                clean.append(None)
            generated.add(doc)
        values=metrics(clean,{label['target_doc_id']},k)
        per_user[label['user_key']].append(values)
        for group in ['user:'+label['user_group'],'item:'+label['item_group']]:
            per_group[group][label['user_key']].append(values)
    names=['recall','ndcg','mrr']
    def macro(users: dict) -> dict:
        return {name+'@'+str(k):sum(sum(v[name] for v in values)/len(values) for values in users.values())/len(users) for name in names}
    count=len(labels)
    return {'events':count,'users':len(per_user),'user_macro':macro(per_user),
            'event_micro':{name+'@'+str(k):sum(v[name] for rows in per_user.values() for v in rows)/count for name in names},
            'groups':{g:{'events':sum(map(len,u.values())),'users':len(u),'user_macro':macro(u)} for g,u in per_group.items()},
            'valid_slot_rate':legal_slots/(count*k),'unique_valid_slot_rate':unique_slots/(count*k),
            'duplicate_slot_rate':duplicate_slots/(count*k),'denominator':'all original positive events; macro within user then users'}


def require_run_lock(lock: dict, protocol_sha: str, catalog_sha: str) -> None:
    required={'protocol_sha256','catalog_sha256','base_model_revision','base_weights_sha256','tokenizer_sha256',
              'content_mapping_sha256','shuffled_mapping_sha256','ordered_training_sample_ids_sha256',
              'optimizer_updates','effective_batch','seed_schedule','input_target_token_id_contract',
              'precision','optimizer','learning_rate','checkpoint_steps','beam_size','resource_preflight_passed',
              'real_tokenizer_and_decode_preflight_passed','frozen_before_training'}
    if not required.issubset(lock) or any(lock[k] is None or lock[k]=='' for k in required):
        raise ValueError('Exact training run not frozen; fill model, mappings, data order, budget and preflight')
    if lock['protocol_sha256']!=protocol_sha or lock['catalog_sha256']!=catalog_sha or lock['beam_size']!=10:
        raise ValueError('Run lock does not match the frozen evaluation contract')
    if not all(lock[k] is True for k in ['resource_preflight_passed','real_tokenizer_and_decode_preflight_passed','frozen_before_training']):
        raise ValueError('Resource and real-token decoding gates required before training')
