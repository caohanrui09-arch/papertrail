"""Validate filtering semantics against the frozen original implementation."""
import unittest
from datetime import timedelta

import numpy as np

from tests.test_expansion import fixture
from gsearch.indexed_expansion import IndexedExpansionRecommender
from gsearch.expansion_recommendation import signature
from gsearch.catalog_audit import stamp


class IndexedExpansionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = fixture()
        cls.fast = IndexedExpansionRecommender(cls.original)

    def test_all_users_all_admission_boundaries_and_timezones(self):
        original, fast = self.original, self.fast
        points = {original.cutoff}
        for row in original.by_id.values():
            at = stamp(row['available_at'])
            for offset in (-1, 0, 1):
                if at + timedelta(microseconds=offset) >= original.cutoff:
                    points.add(at + timedelta(microseconds=offset))
        for at in points:
            for user in (*original.sar.seen, 'unseen-user'):
                expected = original.eligible(user, at)
                for value in (at, at.isoformat(), at.astimezone(stamp('2024-04-10T08:00:00+08:00').tzinfo)):
                    actual = fast.eligible(user, value)
                    self.assertEqual(actual.dtype, np.int32)
                    np.testing.assert_array_equal(actual, expected)

    def test_full_rankings_endpoints_empty_candidates_and_ties(self):
        original, fast = self.original, self.fast
        for user in (*original.sar.seen, 'unseen-user'):
            for at in ('2024-03-01', '2024-04-10'):
                for method in ('popular', 'sar', 'content', 'hybrid'):
                    for alpha in (0, .25, .5, .75, 1):
                        np.testing.assert_array_equal(fast.rank_indices(user, at, method, 100, alpha),
                                                      original.rank_indices(user, at, method, 100, alpha))
        # Every candidate seen, including negative interactions, must produce empty output.
        model = fixture()
        model.sar.seen['all-seen'] = set(model.catalog)
        masked = IndexedExpansionRecommender(model)
        self.assertEqual(masked.recommend('all-seen', '2024-04-10'), [])

    def test_no_fit_mutation_and_no_request_state_leak(self):
        original, fast = self.original, self.fast
        before = signature(original)
        self.assertIs(fast.sar, original.sar)
        self.assertIs(fast.documents, original.documents)
        actual = fast.eligible('alice', '2024-04-10')
        actual[:] = -1
        np.testing.assert_array_equal(fast.eligible('alice', '2024-04-10'), original.eligible('alice', '2024-04-10'))
        self.assertEqual(before, signature(fast))
        self.assertEqual(fast.index_stats['array_payload_bytes'], fast.index_stats['positions'] * 4)
        with self.assertRaises(ValueError):
            fast.eligible('alice', '2024-02-01')


if __name__ == '__main__':
    unittest.main()
