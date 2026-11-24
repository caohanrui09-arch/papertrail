import math
import unittest

import torch

from gsearch.sid_health_probe import BeamObserver,paired_rank_metrics,token_diagnostics,parameter_fingerprint


class ReadOnlyTensorChecks(unittest.TestCase):
    def priors(self):
        return [{'allowed_ids':[1,2],'pilot_counts':{'1':1,'2':1},'total':2,'alpha':1.0} for _ in range(5)]

    def test_observer_returns_identical_score_object(self):
        observer=BeamObserver();scores=torch.tensor([[0.1,float('-inf'),0.3]])
        before=scores.clone();output=observer(torch.tensor([[0,11]]),scores)
        self.assertIs(output,scores)
        self.assertTrue(torch.equal(before,scores))

    def test_observer_records_only_prefixes_and_counts(self):
        observer=BeamObserver()
        observer(torch.tensor([[0],[0]]),torch.tensor([[1.,float('-inf')],[0.,2.]]))
        self.assertEqual(observer.steps,[{'prefixes':[[0],[0]],'finite_branch_counts':[1,2]}])

    def test_identical_lists(self):
        ranking=list(map(str,range(10)));value=paired_rank_metrics(ranking,ranking)
        self.assertEqual(value['jaccard'],1)
        self.assertEqual(value['footrule_missing_rank11_div110'],0)
        self.assertTrue(value['ordered_equal'])

    def test_disjoint_lists(self):
        value=paired_rank_metrics(list(map(str,range(10))),list(map(str,range(10,20))))
        self.assertEqual(value['shared_items'],0)
        self.assertEqual(value['jaccard'],0)
        self.assertEqual(value['footrule_missing_rank11_div110'],1)

    def test_reversal_has_same_set_different_ranks(self):
        ranking=list(map(str,range(10)));value=paired_rank_metrics(ranking,ranking[::-1])
        self.assertEqual(value['jaccard'],1)
        self.assertFalse(value['top1_equal'])
        self.assertAlmostEqual(value['footrule_missing_rank11_div110'],50/110)

    def test_duplicate_or_incomplete_list_rejected(self):
        with self.assertRaises(ValueError):paired_rank_metrics(['x']*10,list(map(str,range(10))))

    def test_uniform_logits_nll_mass_and_prior(self):
        values=token_diagnostics(torch.zeros(2,5,8),torch.ones(2,5,dtype=torch.long),self.priors())
        for sample in values:
            for position in sample:
                self.assertAlmostEqual(position['full_vocab_nll'],math.log(8),places=6)
                self.assertAlmostEqual(position['position_conditional_nll'],math.log(2),places=6)
                self.assertAlmostEqual(position['position_mass'],0.25,places=6)
                self.assertAlmostEqual(position['pilot_position_prior_nll'],math.log(2),places=6)

    def test_target_outside_codebook_rejected(self):
        with self.assertRaises(ValueError):token_diagnostics(torch.zeros(1,5,8),torch.full((1,5),7),self.priors())

    def test_singleton_eos_conditional_is_trivial_not_full_probability(self):
        priors=self.priors();priors[-1]={'allowed_ids':[1],'pilot_counts':{'1':2},'total':2,'alpha':1.0}
        values=token_diagnostics(torch.zeros(1,5,8),torch.ones(1,5,dtype=torch.long),priors)[0][-1]
        self.assertEqual(values['position_conditional_nll'],0)
        self.assertAlmostEqual(values['position_mass'],1/8)
        self.assertAlmostEqual(values['full_vocab_nll'],math.log(8),places=6)

    def test_parameter_digest_detects_changed_parameter(self):
        layer=torch.nn.Linear(2,2).requires_grad_(False)
        before=parameter_fingerprint(layer)
        self.assertEqual(before,parameter_fingerprint(layer))
        with torch.no_grad():layer.weight.add_(1)
        self.assertNotEqual(before,parameter_fingerprint(layer))


if __name__=='__main__':unittest.main()
