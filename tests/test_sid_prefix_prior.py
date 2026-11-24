import json
import math
import unittest
from gsearch.sid_prefix_prior import fit_prefix_counts,context_prior,query_prefix
from gsearch.sid_prior_probe import prior_nll


class PrefixPriorBoundaries(unittest.TestCase):
    def setUp(self):
        self.a=[11,21,31,41,1];self.b=[12,22,32,42,1]
        self.allowed=[[11,12],[21,22],[31,32],[41,42],[1]]
        self.tables=fit_prefix_counts([self.a]*3+[self.b],self.allowed)

    def test_observed_prefix_laplace(self):
        self.assertAlmostEqual(query_prefix(self.tables[1],[11],21)['nll'],math.log(5)-math.log(4))
    def test_first_position_is_marginal(self):
        p=context_prior(self.tables[0],[])
        self.assertEqual(p['total'],4)
        self.assertEqual(p['label_counts'],{'11':3,'12':1})
    def test_unseen_prefix_uniform_without_backoff(self):
        row=query_prefix(self.tables[2],[11,22],31)
        self.assertEqual(row['context_total'],0)
        self.assertAlmostEqual(row['nll'],math.log(2))
    def test_eos_singleton_always_trivial(self):
        self.assertEqual(query_prefix(self.tables[4],[11,21,31,41],1)['nll'],0)
        self.assertEqual(query_prefix(self.tables[4],[11,22,31,42],1)['nll'],0)
    def test_probabilities_normalized_for_seen_and_unseen(self):
        for prefix in [[11],[99]]:
            p=context_prior(self.tables[1],prefix)
            self.assertAlmostEqual(sum(math.exp(-prior_nll(p,t)) for t in p['allowed_ids']),1)
    def test_bad_prefix_length_rejected(self):
        with self.assertRaises(ValueError):context_prior(self.tables[2],[11])
    def test_outside_token_rejected(self):
        with self.assertRaises(ValueError):fit_prefix_counts([[99,21,31,41,1]],self.allowed)
    def test_bad_target_length_rejected(self):
        with self.assertRaises(ValueError):fit_prefix_counts([[11,21,31,1]],self.allowed)
    def test_context_uses_only_previous_tokens(self):
        self.assertEqual(context_prior(self.tables[1],[11])['total'],3)
        self.assertEqual(context_prior(self.tables[1],[12])['total'],1)
        self.assertEqual(context_prior(self.tables[0],[])['total'],4)
    def test_serialized_counts_query_identical(self):
        restored=json.loads(json.dumps(self.tables))
        self.assertEqual(query_prefix(restored[2],[11,21],31),query_prefix(self.tables[2],[11,21],31))


if __name__=='__main__':unittest.main()
