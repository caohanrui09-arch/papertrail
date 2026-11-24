"""Descriptive terminal-output concentration, using saved IDs only."""
from collections import Counter
from pathlib import Path

from gsearch.quality_protocol import digest,save
from gsearch.supervision import json_rows
from scripts.audit_sid_failures import read,predictions_by_user


def describe(users: dict,cohort: list[str],mapping: dict|None=None) -> dict:
    lists=[users[u] for u in cohort]
    slots=[doc for row in lists for doc in row]
    top1=Counter(row[0] for row in lists)
    result={'users':len(cohort),'unique_recommended_papers':len(set(slots)),
        'unique_ordered_top10_lists':len({tuple(row) for row in lists}),
        'largest_top1_user_fraction':max(top1.values())/len(cohort)}
    if mapping is not None:
        prefix=Counter(mapping[d][0] for d in slots)
        result.update(unique_first_prefixes_in_outputs=len(prefix),
                      largest_first_prefix_slot_fraction=max(prefix.values())/len(slots))
    return result


def main() -> None:
    root=Path('reports/stage46');output=root/'output-concentration.json'
    if output.exists():raise FileExistsError('Preserve concentration probe')
    plan=read(root/'supplement-plan.json')
    labels=list(json_rows(Path('data/stage44-supervision/tuning.labels.jsonl')))
    profiles={p['user_key']:p for p in json_rows(Path('data/stage44-supervision/profiles.jsonl'))}
    all_users=sorted({r['user_key'] for r in labels if profiles.get(r['user_key'],{}).get('eligible_train_positive_count',0)>0})
    conditional=sorted({r['user_key'] for r in labels if r['rankable'] and profiles.get(r['user_key'],{}).get('eligible_train_positive_count',0)>0})
    maps={a:read(Path('data/stage45-sft')/(a+'.tokens.json')) for a in ['content','shuffled']}
    methods={m:predictions_by_user(Path('data/stage45-sft')/(m+'.tuning.predictions.jsonl'),labels) for m in ['popular','content','sar']}
    methods.update({p.parent.name:predictions_by_user(p,labels) for p in Path('runs/stage45').glob('*/tuning.predictions.jsonl')})
    result={}
    for method,users in methods.items():
        mapping=maps[method.split('-')[0]] if '-' in method else None
        result[method]={'all_context_users':describe(users,all_users,mapping),
                        'rankable_context_users':describe(users,conditional,mapping)}
    counts=Counter(tuple(row[:3]) for row in maps['content'].values())
    unchanged_events=[]
    for row in labels:
        user=row['user_key'];doc=row['target_doc_id']
        if row['rankable'] and user in conditional and counts[tuple(maps['content'][doc][:3])]>1:
            unchanged_events.append(any(maps['content'][d]!=maps['shuffled'][d] for d in profiles[user]['history_doc_ids']))
    save(output,{'supplement_plan_sha256':digest(root/'supplement-plan.json'),'metrics':result,
        'unchanged_collision_target_events':len(unchanged_events),
        'unchanged_collision_target_events_with_changed_history':sum(unchanged_events),
        'interpretation':plan['causal_limit'],'no_new_predictions':True})
    print({'concentration':result,'unchanged_collision_events':len(unchanged_events),
           'with_changed_history':sum(unchanged_events)},flush=True)


if __name__=='__main__':main()
