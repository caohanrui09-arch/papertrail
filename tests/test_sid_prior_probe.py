from collections import Counter
import math
import unittest
from gsearch.sid_prior_probe import build_priors,legacy_adapter,prior_nll,rescore_reference


class PriorContracts(unittest.TestCase):
    def setUp(self):
        self.mapping={'a':[11,21,31,41,1],'b':[12,22,32,41,1]}
        self.old=build_priors(self.mapping,Counter(a=3,b=1))
        self.expanded=build_priors(self.mapping,Counter(a=4,b=4))

    def test_counts_total_and_levels(self):
        self.assertEqual(len(self.old),5)
        self.assertTrue(all(sum(p['label_counts'].values())==4 for p in self.old))
    def test_eos_singleton_is_trivial(self):self.assertEqual(prior_nll(self.old[-1],1),0)
    def test_zero_label_allowed_token_smoothed(self):
        p=build_priors(self.mapping,Counter(a=4))[0]
        self.assertAlmostEqual(prior_nll(p,12),math.log(6))
    def test_invalid_source_counts_rejected(self):
        for counts in [Counter(),Counter(x=1),Counter(a=-1),Counter(a=1.2)]:
            with self.assertRaises(ValueError):build_priors(self.mapping,counts)
    def test_invalid_eos_or_length_rejected(self):
        with self.assertRaises(ValueError):build_priors({'a':[2,3,4,1]},Counter(a=1))
        with self.assertRaises(ValueError):build_priors({'a':[2,3,4,5,7]},Counter(a=1))
    def test_adapter_copies_and_labels_legacy_key(self):
        adapted=legacy_adapter(self.expanded);adapted[0]['pilot_counts']['11']=900
        self.assertEqual(self.expanded[0]['label_counts']['11'],4)
        self.assertEqual(adapted[0]['total'],8)
    def test_common_prior_independent_of_model(self):
        self.assertEqual(prior_nll(self.expanded[0],11),prior_nll(self.expanded[0],12))
        self.assertNotEqual(prior_nll(self.old[0],11),prior_nll(self.expanded[0],11))
    def test_rescore_preserves_losses_and_rejects_bad_reference(self):
        positions=[{'target_token_id':t,'full_vocab_nll':7.,'position_conditional_nll':3.,
                    'pilot_position_prior_nll':prior_nll(self.old[i],t)} for i,t in enumerate(self.mapping['a'])]
        sample={'sample_id':'fixed','positions':positions}
        result=rescore_reference(sample,self.old,self.expanded)
        self.assertEqual(result['positions'][0]['full_vocab_nll'],7.)
        self.assertAlmostEqual(result['positions'][0]['label4096_position_prior_nll'],math.log(2))
        self.assertNotIn('pilot_position_prior_nll',result['positions'][0])
        positions[0]['pilot_position_prior_nll']+=1
        with self.assertRaises(ValueError):rescore_reference(sample,self.old,self.expanded)


if __name__=='__main__':unittest.main()
