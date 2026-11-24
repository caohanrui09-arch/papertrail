"""Equivalent fixed-profile validation; metric implementation remains stage44's."""
from .supervision import score_rows
from .supervision_evaluation import evaluate


def accelerated_evaluate(labels: list[dict], predictions: list[dict], profiles: dict,
                         catalog: dict, k: int, popularity: dict) -> dict:
    """Deduplicate ONLY static validation, never events, positions or metric inputs."""
    by_qid={row['qid']:row for row in labels}
    representatives={}
    for prediction in predictions:
        if prediction.get('qid') not in by_qid:
            raise ValueError('Unknown evaluation qid')
        label=by_qid[prediction['qid']];user=label['user_key']
        if user in representatives:
            if representatives[user][1].get('doc_ids')!=prediction.get('doc_ids'):
                raise ValueError('Fixed profile received different predictions')
        else:
            representatives[user]=(label,prediction)
    # Native common-popularity and fixed-profile rules, once per immutable profile.
    evaluate([pair[0] for pair in representatives.values()],
             [pair[1] for pair in representatives.values()],profiles,catalog,k,popularity)
    # Native full-event formula and completeness checks, with original order intact.
    result=score_rows(labels,predictions,profiles,catalog,k)
    result['source_user_event_counts']={
        'new_to_source_training':sum(row['user_key'] not in profiles for row in labels),
        'existing_without_catalog_positive_context':sum(row['user_key'] in profiles and profiles[row['user_key']]['eligible_train_positive_count']==0 for row in labels),
        'existing_with_catalog_context':sum(row['user_key'] in profiles and profiles[row['user_key']]['eligible_train_positive_count']>0 for row in labels)}
    return result
