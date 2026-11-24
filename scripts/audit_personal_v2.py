"""Audit catalog identity and independently recompute personalized vector scores."""
import hashlib
import json
from pathlib import Path
import numpy as np
from gsearch.personal_search_v2 import SearchV2, V2Catalog
from gsearch.quality_protocol import digest, save


def main() -> None:
    catalog = V2Catalog(SearchV2())
    old_rows = json.loads(Path('data/stage13-expansion/documents.json').read_text(encoding='utf-8'))
    old = {row['doc_id']: row for row in old_rows}
    overlap = sorted(set(old) & set(catalog.catalog))
    ids = ['2206.02743', '1507.08439']
    snapshot = {'revision': 17, 'items': {doc: 'like' for doc in ids}}
    result = catalog.recommend(snapshot)
    dense = catalog.documents.toarray()
    vector = dense[[catalog.position[doc] for doc in ids]].sum(axis=0)
    vector /= np.linalg.norm(vector)
    scores = dense @ vector
    eligible = [i for i, doc in enumerate(catalog.catalog) if doc not in ids]
    expected = sorted(eligible, key=lambda i: (-scores[i], i))[:6]
    expected = [i for i in expected if scores[i] > 0]
    assert [p['doc_id'] for p in result['papers']] == [catalog.catalog[i] for i in expected]
    checks = []
    for paper, index in zip(result['papers'], expected):
        assert np.isclose(paper['score'], scores[index], rtol=1e-12, atol=1e-12)
        explanation = paper['explanation']
        assert np.isclose(explanation['all_term_contribution_sum'], scores[index], rtol=1e-12, atol=1e-12)
        assert np.isclose(explanation['all_anchor_contribution_sum'], scores[index], rtol=1e-12, atol=1e-12)
        checks.append({'doc_id': paper['doc_id'], 'score': paper['score'], 'anchors': [p['doc_id'] for p in explanation['anchors']]})
    assert not catalog.recommend({'revision': 0, 'items': {}})['papers']
    assert not catalog.recommend({'revision': 1, 'items': {ids[0]: 'hide'}})['papers']
    identities = [{**catalog.paper(doc), 'abstract_sha256': hashlib.sha256(catalog.by_id[doc]['abstract'].encode()).hexdigest()}
                  for doc in catalog.catalog]
    save(Path('reports/stage35/catalog-adaptation.json'), {
        'old_count': len(old), 'new_count': len(catalog.catalog), 'overlap_ids': overlap,
        'overlap_identity_checks': [{ 'doc_id': doc, 'same_version_key': old[doc]['version_key'] == catalog.by_id[doc]['version_key'],
                                      'same_title': old[doc]['title'] == catalog.by_id[doc]['title'],
                                      'same_abstract': old[doc]['abstract'] == catalog.by_id[doc]['abstract']} for doc in overlap],
        'catalog_key': catalog.catalog_key, 'model_signature': catalog.signature, 'identities': identities,
        'reused_code': {p: digest(Path(p)) for p in ['gsearch/visitor_profile.py', 'gsearch/search_v2_workbench.py']},
        'old_preferences_imported': False, 'separate_database_namespace': True,
        'text_representation': 'reuse SearchV2 frozen42 title/abstract TFIDF, not the old10000 matrix',
        'zero_profile_policy': 'explicit needs-likes, no invented v2 popularity',
        'recommendation_display_policy': 'positive content scores only, at most6, excludes all feedback IDs',
        'quality_transfer_claimed': False,
    })
    save(Path('reports/stage35/numerical-validation.json'), {'status': 'passed', 'two_like_independent_dense_scores': checks,
         'all_term_and_anchor_contribution_sums_match': True, 'zero_and_negative_only_explicitly_empty': True})
    print(json.dumps({'status': 'passed', 'identity_count': len(identities), 'overlap': overlap, 'independent_scores': len(checks)}))


if __name__ == '__main__':
    main()
