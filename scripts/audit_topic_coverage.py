"""Offline corpus and synthetic-profile diagnostics; no serving or label writes."""
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

import pandas as pd

from gsearch.quality_protocol import digest, save

ROOT = Path('data/stage28-coverage')
REPORT = Path('reports/stage28')
PATTERNS = {
    'generative': r'generativ.{0,60}retriev|differentiable.{0,20}(index|retriev)|document.{0,15}(identif|index)|doc[ -]?ids?\b|neural corpus|autoregress.{0,50}retriev',
    'recommendation': r'\brecommend(?:ation|er|ing|s)?\b|collaborative filter',
    'cold': r'cold[ -]?start|new items?|unseen items?|zero[ -]?interaction|no.{0,16}interaction',
    'bias': r'exposure|propensit|counterfactual|unbiased|missing.not.at.random|unobserved',
}
ANCHORS = [
    ('2202.06991','generative','Transformer Memory as a Differentiable Search Index','2022-02-14'),
    ('2206.02743','generative','A Neural Corpus Indexer for Document Retrieval','2022-06-06'),
    ('1507.08439','cold','Metadata Embeddings for User and Item Cold-start Recommendations','2015-07-30'),
    ('1510.07025','bias','Modeling User Exposure in Recommendation','2015-10-23'),
    ('1602.05352','bias','Recommendations as Treatments: Debiasing Learning and Evaluation','2016-02-17'),
    ('1003.5956','bias','An Unbiased, Data-Driven, Offline Evaluation Method of Contextual Bandit Algorithms','2010-03-31'),
]


def load(path: str | Path) -> object:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main() -> None:
    if ROOT.exists() or REPORT.exists():
        raise ValueError('Preserve the prior diagnostic version')
    source = Path('data/stage13-expansion/documents.json')
    receipt = load('reports/stage13/corpus-receipt.json')
    assert digest(source) == receipt['documents_sha256']
    records = load(source); by_id = {r['doc_id']: r for r in records}
    assert len(records) == len(by_id) == 10000
    assert set(load('data/stage13-expansion/catalog-10000.json')) == set(by_id)
    qs = [q for q in load('data/stage25-requirements/queries-v2-proposal.json') if q['inherited_split'] == 'tuning']
    tasks = load('data/stage26-annotation/blind/tasks.json')
    at = qs[0]['at']; when = datetime.fromisoformat(at)
    assert len(qs) == 9 and all(q['at'] == at for q in qs)
    assert all(q['query_id'] in tasks for q in qs)
    files = [source, Path('data/stage13-expansion/catalog-10000.json'),
        Path('data/stage13-expansion/pool.json'), Path('data/stage9-recommendation/train.csv'),
        Path('data/stage20-quality/evaluator/profiles-private.json'),
        Path('data/stage25-requirements/queries-v2-proposal.json'),
        Path('data/stage26-annotation/blind/tasks.json'),
        Path('scripts/prepare_quality_queries.py'),Path('scripts/refine_query_requirements.py'),
        Path('scripts/build_annotation_pool.py'),Path('gsearch/quality_retrieval.py'),
        Path('gsearch/unified_search.py'),Path('gsearch/expansion_data.py')]
    save(ROOT/'input-manifest.json', {'scope':'post-model-review diagnostic, no quality evaluation or tuning',
        'at':at,'patterns':PATTERNS,'files':{str(p):digest(p) for p in files},
        'screening_not_exhaustive_semantic_review':True,'anchor_selection':'illustrative known references verified on official arXiv pages; not exhaustive ground truth'})
    train = pd.read_csv('data/stage9-recommendation/train.csv', dtype={'user_id':str,'arxiv_id':str})
    available = {d for d,r in by_id.items() if datetime.fromisoformat(r['available_at']) <= when}
    likes = train[(train.rating == 1) & train.arxiv_id.isin(available)].groupby('user_id').arxiv_id.agg(set).to_dict()
    seen = train.groupby('user_id').arxiv_id.agg(set).to_dict()
    key = lambda text: hashlib.sha256(('stage20-draft-v1:'+text).encode()).hexdigest()
    users = sorted((u for u, ds in likes.items() if len(ds) >= 5), key=key)
    profiles = load('data/stage20-quality/evaluator/profiles-private.json')
    old_queries = {q['query_id']:q for q in load('data/stage20-quality/inputs/queries.json')}
    profile_audit = []
    for q in qs:
        parent = old_queries[q['parent_query_id']]
        position = (int(parent['query_id'].split('-')[1])-1)//3
        profile = profiles[q['source_profile_id']]
        expected_user = users[position]
        expected_history = sorted(likes[expected_user], key=key)[:5]
        assert profile['user_id'] == expected_user and profile['history_doc_ids'] == expected_history
        assert parent['profile_id'] == q['source_profile_id']
        shown = [p['doc_id'] for p in tasks[q['query_id']]['context']]
        assert shown == ([] if q['intent'] == 'topic' else expected_history)
        profile_audit.append({'query_id':q['query_id'],'parent_query_id':parent['query_id'],
            'family':q['topic_family'],'profile_id':q['source_profile_id'],'private_user_id':expected_user,
            'hash_sorted_user_position':position,'history_ids':expected_history,'shown_history_ids':shown,
            'hash_reproduction_passed':True,'all_history_train_positive_and_available':True,
            'topic_history_semantic_matching_in_selection':False,
            'profile_origin':profile['origin'],
            'history':[{'doc_id':d,'title':by_id[d]['title'],'available_at':by_id[d]['available_at']} for d in expected_history]})
    save(ROOT/'profile-provenance.json', profile_audit)
    scan = defaultdict(list)
    all_hits = {}
    for r in records:
        text = re.sub(r'\s+', ' ', r['title']+' '+r['abstract'])
        for name, pattern in PATTERNS.items():
            if re.search(pattern, text, re.I):
                scan[name].append(r['doc_id'])
                if name != 'bias' or re.search(PATTERNS['recommendation']+r'|\bbandit\b|ranking', text, re.I):
                    all_hits[r['doc_id']] = r
    prior = {r['paper']['doc_id'] for r in load('data/stage27-model-review/paper-reader.json')}
    screen = [{'paper':r,'matches':[k for k,v in scan.items() if r['doc_id'] in v],
        'already_read_stage27':r['doc_id'] in prior,'available_at_query':r['doc_id'] in available,
        'seen_by_query':{q['query_id']:r['doc_id'] in seen[profiles[q['source_profile_id']]['user_id']] for q in qs}}
        for r in all_hits.values()]
    save(ROOT/'screening-papers.json', screen)
    save(ROOT/'screening-new-reader.json', [r for r in screen if not r['already_read_stage27']])
    pool = load('data/stage13-expansion/pool.json')
    state = load('data/stage13-expansion/acquisition-state.json')
    anchors = []
    for doc, group, title, published in ANCHORS:
        warm_index = pool['warm'].index(doc) if doc in pool['warm'] else None
        old_index = pool['old_cold'].index(doc) if doc in pool['old_cold'] else None
        anchors.append({'doc_id':doc,'family':group,'title':title,'official_v1_url':f'https://arxiv.org/abs/{doc}v1',
            'v1_date':published,'published_before_query':published < at[:10],
            'in_frozen_catalog':doc in by_id,'in_warm_preselection_rank':None if warm_index is None else warm_index+1,
            'in_old_cold_hash_pool_rank':None if old_index is None else old_index+1,
            'incoming_days':[day for day, ids in pool['new_days'].items() if doc in ids],
            'acquisition_processed':doc in state['processed'],
            'acquisition_rejections':[r for r in state['rejected'] if r['doc_id'] == doc],
            'seen_by_query':{q['query_id']:doc in seen[profiles[q['source_profile_id']]['user_id']] for q in qs}})
    save(ROOT/'reference-membership.json', anchors)
    stats = {'catalog':len(records),'available_at_query':len(available),
        'unavailable_ids':sorted(set(by_id)-available),'pattern_counts':{k:len(v) for k,v in scan.items()},
        'screened_union':len(screen),'new_abstracts_to_read':sum(not r['already_read_stage27'] for r in screen),
        'primary_categories':dict(Counter(r['primary_category'] for r in records)),
        'category_memberships':dict(Counter(c for r in records for c in r['categories'])),
        'anchor_count':len(anchors),'anchors_in_catalog':sum(r['in_frozen_catalog'] for r in anchors),
        'profile_query_checks':len(profile_audit),'all_hash_reproductions_passed':True}
    save(REPORT/'corpus-profile-summary.json', stats)
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == '__main__':
    main()
