"""CPU-only prior bookkeeping for unchanged native stage47 probe adapters."""
from collections import Counter
import math
from pathlib import Path
import json

ROOT=Path('reports/stage50')
DATA=Path('data/stage50-health')


def read(path: Path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def build_priors(mapping: dict,counts: Counter) -> list[dict]:
    if not mapping or any(len(v)!=5 or v[-1]!=1 for v in mapping.values()):
        raise ValueError('Five-token EOS mapping required')
    if not counts or any(d not in mapping or type(n) is not int or n<1 for d,n in counts.items()):
        raise ValueError('Positive source-only label counts required')
    total=sum(counts.values());result=[]
    for position in range(5):
        allowed=sorted({v[position] for v in mapping.values()});tokens=Counter()
        for doc,n in counts.items():tokens[mapping[doc][position]]+=n
        result.append({'position':position,'allowed_ids':allowed,'label_counts':{str(t):tokens[t] for t in allowed},
            'total':total,'alpha':1.0})
    return result


def prior_nll(prior: dict,target: int) -> float:
    if target not in prior['allowed_ids']:raise ValueError('Target outside prior codebook')
    return math.log(prior['total']+len(prior['allowed_ids'])*prior['alpha'])-math.log(prior['label_counts'][str(target)]+prior['alpha'])


def legacy_adapter(priors: list[dict]) -> list[dict]:
    """Only the stage47 helper argument uses its old pilot_counts key."""
    return [{'position':p['position'],'allowed_ids':list(p['allowed_ids']),'pilot_counts':dict(p['label_counts']),
             'total':p['total'],'alpha':p['alpha']} for p in priors]


def rescore_reference(sample: dict,old: list[dict],expanded: list[dict]) -> dict:
    result={k:v for k,v in sample.items() if k!='positions'};positions=[]
    for index,row in enumerate(sample['positions']):
        original=prior_nll(old[index],row['target_token_id'])
        if abs(original-row['pilot_position_prior_nll'])>1e-12:raise ValueError('Old prior does not match frozen reference')
        value={k:v for k,v in row.items() if k!='pilot_position_prior_nll'}
        value['label1024_position_prior_nll']=original
        value['label4096_position_prior_nll']=prior_nll(expanded[index],row['target_token_id'])
        predict=min(expanded[index]['allowed_ids'],key=lambda t:(-expanded[index]['label_counts'][str(t)],t))
        value['label4096_prior_top1_correct']=predict==row['target_token_id']
        positions.append(value)
    result['positions']=positions
    return result
