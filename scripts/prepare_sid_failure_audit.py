"""Prepare or verify the supplementary audit plan without overwriting results."""
import json
from pathlib import Path

from gsearch.quality_protocol import save


def main() -> None:
    root=Path('reports/stage46');root.mkdir(parents=True,exist_ok=True)
    path=root/'supplement-plan.json'
    plan={'scope':'posthoc descriptive output-diversity and history-mapping check; no new ranking/model inference',
        'defined_before_calculating_supplement':True,
        'groups':['all_unique_users_with_frozen_positive_context','unique_users_in_rankable_context_events'],
        'measures':['unique_top10_papers','unique_ordered_top10_lists','largest_top1_user_share',
                    'final_first_prefix_occupancy','unchanged_target_collision_events_with_changed_history'],
        'causal_limit':'Observed output concentration cannot establish history insensitivity without a counterfactual history probe',
        'selection_limit':'No event/topic/target sampling or candidate expansion using future likes'}
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8'))==plan
        print({'existing_plan_verified':True})
        return
    if (root/'output-concentration.json').exists():raise ValueError('Plan must precede supplementary calculation')
    save(path,plan)
    print({'plan':'prepared'})


if __name__=='__main__':main()
