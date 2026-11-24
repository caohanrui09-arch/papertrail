"""Source-only deterministic probe sampling; no model imports or future labels."""
from collections import Counter
import hashlib

import numpy as np
from scipy.optimize import linear_sum_assignment


def source_key(kind: str,identity: str) -> str:
    return hashlib.sha256(('stage47-source-only-20261104:'+kind+':'+identity).encode()).hexdigest()


def same_length_swap(rows: list[dict]) -> list[int]:
    """Use SciPy's assignment, not a custom matching algorithm."""
    if len(rows)<2 or len({len(r['history_doc_ids']) for r in rows})!=1:
        raise ValueError('At least two equal-length histories required')
    count=len(rows);cost=np.full((count,count),1e6,dtype=float)
    for i,left in enumerate(rows):
        for j,right in enumerate(rows):
            if i!=j and left['history_doc_ids']!=right['history_doc_ids']:
                cost[i,j]=int(source_key('donor',left['user_key']+':'+right['user_key'])[:8],16)/2**32
    receivers,donors=linear_sum_assignment(cost)
    if receivers.tolist()!=list(range(count)) or np.any(cost[receivers,donors]>=1e6):
        raise ValueError('No non-identical one-to-one same-length history assignment')
    return donors.tolist()


def select_profiles(profiles: list[dict],lengths: tuple[int,...]=(1,20),per_length: int=16) -> list[dict]:
    result=[]
    for length in lengths:
        candidates=sorted((r for r in profiles if r['eligible_train_positive_count']>0 and len(r['history_doc_ids'])==length),
                          key=lambda r:source_key('profile',r['user_key']))
        if len(candidates)<per_length:raise ValueError('Insufficient source profiles in fixed length stratum')
        chosen=candidates[:per_length];donors=same_length_swap(chosen)
        for i,row in enumerate(chosen):
            donor=chosen[donors[i]]
            result.append({'user_key':row['user_key'],'history_length':length,
                'source_hash':source_key('profile',row['user_key']),
                'original_history_doc_ids':row['history_doc_ids'],'swapped_history_doc_ids':donor['history_doc_ids'],
                'donor_user_key':donor['user_key'],'seen_doc_ids':row['seen_doc_ids']})
    return result


def select_prefixes(samples,selected_ids: set[str],per_cell: int=8) -> tuple[list[dict],dict,dict]:
    cells={(group,length):[] for group in ['pilot','pool_not_pilot'] for length in [1,20]}
    pilot_target_counts=Counter();pool_target_counts=Counter()
    for row in samples:
        doc=row['target_doc_id'];pool_target_counts[doc]+=1
        group='pilot' if row['sample_id'] in selected_ids else 'pool_not_pilot'
        if group=='pilot':pilot_target_counts[doc]+=1
        key=(group,len(row['history_doc_ids']))
        if key in cells:cells[key].append(row)
    result=[]
    for (group,length),rows in cells.items():
        if len(rows)<per_cell:raise ValueError('Insufficient strict-history samples in fixed probe cell')
        chosen=sorted(rows,key=lambda r:source_key('prefix',r['sample_id']))[:per_cell]
        for row in chosen:
            if row['target_doc_id'] in row['history_doc_ids']:raise ValueError('Target entered history')
            result.append(row|{'exposure_group':group,'history_length':length,
                              'source_hash':source_key('prefix',row['sample_id'])})
    return result,dict(pilot_target_counts),dict(pool_target_counts)
