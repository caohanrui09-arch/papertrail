"""Offline descriptive audit adapters over frozen predictions, not new ranking."""
from collections import Counter,defaultdict

from .evaluate import metrics


def exposure_group(doc: str, source: dict, eligible: dict, pool: dict, pilot: dict,
                   catalog: set[str]) -> str:
    if doc not in catalog:return 'outside_catalog'
    if source.get(doc,0)==0:return 'no_source_train_like'
    if eligible.get(doc,0)==0:return 'train_liked_without_proxy_eligible_feedback'
    if pool.get(doc,0)==0:return 'eligible_like_without_next_item_target'
    if pilot.get(doc,0)==0:return 'pool_target_not_selected_in_pilot'
    return 'pilot_target_seen'


def availability_group(label: dict, has_context: bool) -> str:
    if not label['rankable']:
        return 'unrankable:'+str(label['miss_reason'])
    return 'rankable_with_context' if has_context else 'rankable_without_context'


def mapping_group(doc: str, content: dict, shuffled: dict, raw_counts: Counter) -> str:
    if doc not in content:return 'outside_catalog'
    if content[doc]!=shuffled[doc]:return 'changed_singleton_target'
    return 'unchanged_collision_target' if raw_counts[tuple(content[doc][:3])]>1 else 'unchanged_singleton_target'


def final_prefix_status(target: list[int], paths: list[list[int]], hit: bool) -> dict:
    """Observe only final paths; no claim about intermediate beam pruning."""
    if not paths or not target or target[-1]!=1 or any(not p or p[-1]!=1 for p in paths):
        raise ValueError('Complete EOS paths required')
    lengths=[]
    for path in paths:
        shared=0
        for left,right in zip(target[:-1],path[:-1]):
            if left!=right:break
            shared+=1
        lengths.append(shared)
    maximum=max(lengths)
    if hit!=(maximum==len(target)-1):
        raise ValueError('Hit and unique SID paths disagree')
    return {'max_shared_sid_prefix_tokens':maximum,
            'first_missing_final_prefix_depth':None if hit else maximum+1,
            'prefix_covered':[any(p[:depth]==target[:depth] for p in paths) for depth in range(1,len(target))],
            'actual_beam_pruning_step_observed':False}


class MetricAccumulator:
    """Use original metrics; group aggregation is user-within-event then users."""
    def __init__(self):
        self.values=defaultdict(lambda:defaultdict(lambda:[0,0.0,0.0,0.0]))
        self.events=Counter();self.hits=Counter()

    def add(self,groups: list[str],user: str,predicted: list[str],target: str) -> bool:
        value=metrics(predicted,{target},10)
        for group in groups:
            row=self.values[group][user]
            row[0]+=1;row[1]+=value['recall'];row[2]+=value['ndcg'];row[3]+=value['mrr']
            self.events[group]+=1;self.hits[group]+=int(value['hit'])
        return bool(value['hit'])

    def export(self) -> dict:
        result={}
        for group,users in sorted(self.values.items()):
            result[group]={'events':self.events[group],'users':len(users),'hit_events':self.hits[group],
                'user_macro':{key:sum(row[index]/row[0] for row in users.values())/len(users)
                              for key,index in [('recall@10',1),('ndcg@10',2),('mrr@10',3)]},
                'event_micro':{key:sum(row[index] for row in users.values())/self.events[group]
                               for key,index in [('recall@10',1),('ndcg@10',2),('mrr@10',3)]}}
        return result


def prefix_coverage(mapping: dict, target_counts: dict, history_counts: dict, pool_counts: dict) -> list[dict]:
    result=[]
    for depth in [1,2,3,4]:
        catalog={tuple(tokens[:depth]) for tokens in mapping.values()}
        labels={tuple(mapping[d][:depth]) for d,n in target_counts.items() if n}
        inputs={tuple(mapping[d][:depth]) for d,n in history_counts.items() if n}
        pool={tuple(mapping[d][:depth]) for d,n in pool_counts.items() if n}
        result.append({'depth':depth,'catalog_prefixes':len(catalog),'full_pool_label_prefixes':len(pool),
            'pilot_label_prefixes':len(labels),'pilot_history_prefixes':len(inputs),
            'pilot_label_catalog_coverage':len(labels)/len(catalog),
            'pilot_label_pool_coverage':len(labels)/len(pool)})
    return result
