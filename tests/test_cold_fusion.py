"""Causal masks, support gates, ties, native normalization and unchanged fallback."""
import unittest

import numpy as np
import pandas as pd

from tests.test_expansion import fixture
from gsearch.cold_fusion import ColdAwareRecommender
from gsearch.expansion_recommendation import signature
from gsearch.catalog_audit import stamp


class ColdFusionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = fixture()
        cls.model = ColdAwareRecommender(cls.original)

    def test_native_normalization_and_missing_branch_formula(self):
        m = self.model
        eligible = np.array([0, 1, 3, 4], dtype=np.int32)
        cf = np.array([0., 4., 0., 0., 0.]); text = np.array([.5, 1., 0., 2., 0.])
        # Native minmax expected values independently from hand-computable extrema.
        a = np.array([0., 1., 0., 0.]); b = np.array([.25, .5, 1., 0.])
        plain = .5 * a + .5 * b
        expected = plain.copy(); expected[2:] = b[2:]
        np.testing.assert_array_equal(m.fused_scores(cf, text, eligible, .5), expected)
        np.testing.assert_array_equal(m.fused_scores(cf, text, eligible, .5, False), plain)
        # A known warm item with score0 is still a supported branch, not boosted as missing.
        self.assertEqual(m.fused_scores(cf, text, eligible, .5)[0], .125)
        self.assertEqual(m.fused_scores(cf, text, eligible, .5)[2], 1.)

    def test_native_normalizer_constant_inputs_and_positive_affine_invariance(self):
        from sklearn.preprocessing import minmax_scale
        values = np.array([0., 0., 1., 4., 4.])
        np.testing.assert_array_equal(minmax_scale(values), np.array([0., 0., .25, 1., 1.]))
        np.testing.assert_allclose(minmax_scale(values * 3 + 7), minmax_scale(values), rtol=0, atol=1e-15)
        m = self.model
        eligible = m.eligible('alice', '2024-04-10')
        zeros = np.zeros(len(m.catalog))
        np.testing.assert_array_equal(m.fused_scores(zeros, zeros, eligible, .5), np.zeros(len(eligible)))

    def test_endpoints_cold_users_and_seen_negative_feedback(self):
        m = self.model
        for user in ('alice', 'bob', 'new-user'):
            for at in ('2024-03-01', '2024-04-10'):
                for method in ('cold_aware', 'score_blend'):
                    np.testing.assert_array_equal(m.rank_indices(user, at, method, alpha=0), m.rank_indices(user, at, 'content'))
                    if user == 'new-user':
                        np.testing.assert_array_equal(m.rank_indices(user, at, method), m.rank_indices(user, at, 'popular'))
                    for hit in m.recommend(user, at, method):
                        self.assertNotIn(hit['doc_id'], m.sar.seen.get(user, set()))
                        self.assertLessEqual(stamp(m.by_id[hit['doc_id']]['available_at']), stamp(at))
        for method in ('popular', 'sar', 'content', 'hybrid'):
            np.testing.assert_array_equal(m.rank_indices('alice', '2024-04-10', method),
                                          self.original.rank_indices('alice', '2024-04-10', method))

    def test_future_extrema_do_not_change_earlier_fusion_or_fit(self):
        m = self.model; changed = ColdAwareRecommender(fixture('biology protein futurepoisonword'))
        for method in ('cold_aware', 'score_blend'):
            np.testing.assert_array_equal(m.rank_indices('alice', '2024-03-10', method), changed.rank_indices('alice', '2024-03-10', method))
        cf, text = m.components('alice'); cf[3] = 1e20; text[3] = 1e20
        for method in ('cold_aware', 'score_blend'):
            np.testing.assert_array_equal(m.rank_indices('alice', '2024-03-10', method, components=(cf, text)),
                                          m.rank_indices('alice', '2024-03-10', method))
        np.testing.assert_array_equal(m.vectorizer.idf_, changed.vectorizer.idf_)

    def test_stable_ties_empty_masks_batch_parity_and_no_mutation(self):
        m = self.model; before = signature(m)
        users = ['alice', 'bob', 'new-user']; a, b = m.batch_components(users)
        for j, user in enumerate(users):
            for method in ('cold_aware', 'score_blend'):
                np.testing.assert_array_equal(m.rank_indices(user, '2024-04-10', method),
                    m.rank_indices(user, '2024-04-10', method, components=(a[j], b[j])))
                eligible = m.eligible(user, '2024-04-10')
                zeros = np.zeros(len(m.catalog))
                np.testing.assert_array_equal(m.rank_indices(user, '2024-04-10', method, components=(zeros, zeros)),
                                              eligible[:10] if user in m.user2row else m.rank_indices(user, '2024-04-10', 'popular'))
                self.assertEqual(len(m.rank_indices(user, '2024-04-10', method, eligible_indices=np.array([], dtype=np.int32))), 0)
        self.assertEqual(before, signature(m))
        with self.assertRaises(ValueError): m.rank_indices('alice', '2024-04-10', 'cold_aware', alpha=1)
        with self.assertRaises(ValueError): m.rank_indices('alice', '2024-02-01', 'cold_aware')

    def test_metric_denominator_keeps_outside_catalog_future_positives(self):
        from unittest.mock import patch
        from gsearch.benchmark_cold_fusion import summarize
        frame = pd.DataFrame([('u1', 'a'), ('u1', 'outside'), ('u2', 'b')], columns=['user_id', 'arxiv_id'])
        receipts = [{'cold_user': False, 'cold_item_global': False, 'available_gold': True},
                    {'cold_user': False, 'cold_item_global': True, 'available_gold': False},
                    {'cold_user': True, 'cold_item_global': True, 'available_gold': True}]
        predictions = np.full((3, 10), -1, dtype=np.int32); predictions[:, 0] = 0
        with patch('gsearch.benchmark_cold_fusion.read', return_value=['a', 'b']):
            result, rows = summarize(predictions, frame, receipts)
        self.assertEqual(result['summary']['positive_events'], 3)
        self.assertEqual(result['summary']['recall@10'], .25)
        self.assertEqual(result['event_groups']['cold_item']['events'], 2)
        self.assertEqual(result['event_groups']['warm_item']['hits'], 1)
        self.assertEqual(rows[0]['relevant'], ['a', 'outside'])

    def test_predeclared_acceptance_rejects_warm_loss_cold_loss_and_cost(self):
        from copy import deepcopy
        from gsearch.benchmark_cold_fusion import acceptance
        baseline = {'summary': {'recall@10': .1, 'ndcg@10': .1},
                    'event_groups': {'cold_item': {'recall': .1, 'ndcg': .1}, 'warm_item': {'recall': .1, 'ndcg': .1}},
                    'user_groups': {'warm_user': {'recall': .1, 'ndcg': .1}}}
        cost = {'mean_ms': 10., 'p95_ms': 20.}
        self.assertTrue(acceptance(baseline, baseline, cost, cost)['passed'])
        for group in ('cold_item', 'warm_item'):
            candidate = deepcopy(baseline); candidate['event_groups'][group]['ndcg'] = .09
            self.assertFalse(acceptance(candidate, baseline, cost, cost)['passed'])
        self.assertFalse(acceptance(baseline, baseline, {'mean_ms': 16., 'p95_ms': 20.}, cost)['passed'])


if __name__ == '__main__':
    unittest.main()
