"""Offline count adapter, reusing the frozen Laplace NLL implementation."""
from collections import Counter,defaultdict
import json
from pathlib import Path

from .sid_prior_probe import prior_nll

ROOT=Path('reports/stage51')
DATA=Path('data/stage51-prefix-prior')


def read(path: Path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def prefix_key(prefix: list[int]) -> str:
    return json.dumps(prefix,separators=(',',':'))


def fit_prefix_counts(labels: list[list[int]],allowed: list[list[int]]) -> list[dict]:
    if not labels or len(allowed)!=5 or any(not a or len(a)!=len(set(a)) for a in allowed):
        raise ValueError('Nonempty labels and five unique codebooks required')
    if any(len(row)!=5 or row[-1]!=1 or any(t not in allowed[j] for j,t in enumerate(row)) for row in labels):
        raise ValueError('Invalid raw SID labels')
    tables=[defaultdict(Counter) for _ in range(5)]
    for row in labels:
        for position,token in enumerate(row):tables[position][prefix_key(row[:position])][token]+=1
    return [{'position':position,'allowed_ids':list(ids),'alpha':1.0,
        'contexts':{key:{'total':sum(counts.values()),'label_counts':{str(t):n for t,n in sorted(counts.items())}}
                    for key,counts in sorted(tables[position].items())}}
            for position,ids in enumerate(allowed)]


def context_prior(level: dict,prefix: list[int]) -> dict:
    if len(prefix)!=level['position']:raise ValueError('Wrong conditioning prefix length')
    row=level['contexts'].get(prefix_key(prefix),{'total':0,'label_counts':{}})
    return {'position':level['position'],'allowed_ids':list(level['allowed_ids']),'alpha':level['alpha'],
        'total':row['total'],'label_counts':{str(t):row['label_counts'].get(str(t),0) for t in level['allowed_ids']}}


def query_prefix(level: dict,prefix: list[int],target: int) -> dict:
    prior=context_prior(level,prefix)
    return {'nll':prior_nll(prior,target),'context_total':prior['total'],
            'target_count':prior['label_counts'][str(target)],'codebook_size':len(prior['allowed_ids']),
            'context_seen':prior['total']>0}
