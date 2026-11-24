"""Offline bookkeeping over native metrics; no model or ranking implementation."""
from collections import Counter, defaultdict
from pathlib import Path
import json

from .evaluate import metrics

ROOT=Path('reports/stage49')
DATA=Path('data/stage49-audit')
TRANSITIONS=['new_hit','lost_hit','retained_up','retained_down','retained_same','both_miss']


def read(path: Path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def exposure(doc: str, items: dict, expanded: Counter) -> str:
    if doc not in items:return 'outside_catalog'
    row=items[doc]
    if row['pilot_label_count']:return 'labelled_first1024'
    if expanded.get(doc,0):return 'newly_labelled_1025_4096'
    if row['full_pool_target_count']:return 'pool_target_still_unselected'
    return row['group']


def frequency_bin(value: int) -> str:
    if value<0:raise ValueError('Negative source count')
    return 'zero' if value==0 else '1to4' if value<5 else '5to19' if value<20 else '20plus'


def rank_of(predicted: list[str], doc: str) -> int | None:
    return predicted.index(doc)+1 if doc in predicted else None


def transition(old_rank: int | None, new_rank: int | None) -> str:
    if any(r is not None and (type(r) is not int or not 1<=r<=10) for r in [old_rank,new_rank]):
        raise ValueError('Expected legal Top10 rank or missing')
    if old_rank is None:return 'both_miss' if new_rank is None else 'new_hit'
    if new_rank is None:return 'lost_hit'
    return 'retained_up' if new_rank<old_rank else 'retained_down' if new_rank>old_rank else 'retained_same'


def weighted_change(user: str, old: list[str], new: list[str], target: str, user_events: Counter) -> dict:
    if user not in user_events or not user_events[user]:raise ValueError('Missing full-denominator user weight')
    left=metrics(old,{target},10);right=metrics(new,{target},10)
    weight=1/(len(user_events)*user_events[user])
    return {name:(right[name]-left[name])*weight for name in ['ndcg','recall','mrr']}


def select_case(candidates: dict, key: str, row: dict) -> None:
    if key not in candidates or row['qid']<candidates[key]['qid']:candidates[key]=row


def output_summary(raw: dict, mapping: dict, items: dict, label_counts: Counter) -> dict:
    rankings=[r['doc_ids'] for r in raw.values() if not r['fallback']]
    counts=Counter(d for r in rankings for d in r);tops=Counter(r[0] for r in rankings)
    if not rankings:raise ValueError('Context users required')
    prefix=[]
    for depth in [1,2,3,4]:
        observed=Counter(tuple(mapping[d][:depth]) for r in rankings for d in r)
        labels=Counter()
        for doc,n in label_counts.items():labels[tuple(mapping[doc][:depth])]+=n
        largest=max(observed,key=lambda key:(observed[key],key))
        prefix.append({'depth':depth,'unique_output_prefixes':len(observed),
            'largest_output_prefix_share':observed[largest]/sum(observed.values()),
            'largest_output_prefix_label_share':labels[largest]/sum(labels.values()),
            'largest_prefix_token_ids':list(largest)})
    return {'context_users':len(rankings),'slots':sum(counts.values()),'unique_papers':len(counts),
        'catalog_coverage':len(counts)/len(mapping),'top1_max_share':max(tops.values())/len(rankings),
        'source_likes_slot_mean':sum(n*items[d]['source_train_likes'] for d,n in counts.items())/sum(counts.values()),
        'label_count_slot_mean':sum(n*label_counts[d] for d,n in counts.items())/sum(counts.values()),
        'label_probability_slot_mean':sum(n*label_counts[d] for d,n in counts.items())/(sum(counts.values())*sum(label_counts.values())),
        'source_frequency_slots':dict(Counter({group:sum(n for d,n in counts.items() if frequency_bin(items[d]['source_train_likes'])==group)
                                            for group in ['zero','1to4','5to19','20plus']})),
        'prefix':prefix}


def concentration(changes: list[dict]) -> dict:
    positive=defaultdict(float);negative=defaultdict(float);papers=defaultdict(float);net=defaultdict(float)
    gains=Counter();losses=Counter()
    for row in changes:
        value=row['weighted_delta']['ndcg'];user=row['user_key'];doc=row['target_doc_id']
        net[user]+=value
        if value>0:positive[user]+=value;papers[doc]+=value
        if value<0:negative[user]-=value
        if row['transition']=='new_hit':gains[doc]+=1
        if row['transition']=='lost_hit':losses[doc]+=1
    total=sum(positive.values())
    def share(counts: dict,k: int) -> float | None:
        return sum(sorted(counts.values(),reverse=True)[:k])/sum(counts.values()) if counts else None
    return {'positive_net_users':sum(v>1e-15 for v in net.values()),'negative_net_users':sum(v< -1e-15 for v in net.values()),
        'gross_positive_ndcg':total,'gross_negative_ndcg':sum(negative.values()),
        'top1_user_share_of_gross_positive':share(positive,1),'top5_users_share_of_gross_positive':share(positive,5),
        'top1_paper_share_of_gross_positive':share(papers,1),'top5_papers_share_of_gross_positive':share(papers,5),
        'unique_new_hit_papers':len(gains),'unique_lost_hit_papers':len(losses),
        'top1_paper_share_new_hit_events':share(gains,1)}
