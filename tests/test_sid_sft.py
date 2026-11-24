"""Boundary checks for raw-token adapters and pre-beam seen filtering."""
import unittest
from pathlib import Path

import torch

from gsearch.sid_sft import (CatalogConstraint, input_tokens, fixed_features,
                            OrderedExamples, DATA, load, json_rows)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.mapping={'a':[100,200,1],'b':[100,201,1],'c':[101,200,1]}
        self.index=CatalogConstraint(self.mapping,None)
        self.index.seen=[set()]

    def allowed(self,path):
        return self.index.allowed(0,torch.tensor(path))

    def test_prefix_children(self):
        self.assertEqual(self.allowed([0]),[100,101])
        self.assertEqual(self.allowed([0,100]),[200,201])

    def test_prune_entire_prefix(self):
        self.index.seen=[{'a','b'}]
        self.assertEqual(self.allowed([0]),[101])

    def test_prune_only_one_leaf(self):
        self.index.seen=[{'a'}]
        self.assertEqual(self.allowed([0,100]),[201])

    def test_eos_only_after_complete_sid(self):
        self.assertEqual(self.allowed([0,100,200]),[1])
        self.assertNotIn(1,self.allowed([0,100]))

    def test_reject_invalid_prefix(self):
        with self.assertRaises(ValueError):self.allowed([0,999])

    def test_reject_no_candidates(self):
        self.index.seen=[set(self.mapping)]
        with self.assertRaises(ValueError):self.allowed([0])

    def test_reject_missing_start(self):
        with self.assertRaises(ValueError):self.allowed([100])

    def test_input_has_no_target_or_user(self):
        self.assertEqual(input_tokens(['a','b'],self.mapping,[77]),[77,100,200,100,201,1])

    def test_bounded_history(self):
        self.assertEqual(len(input_tokens(['a']*25,self.mapping,[77])),42)

    def test_reject_truncation(self):
        with self.assertRaises(ValueError):input_tokens(['a']*20,self.mapping,[77],10)

    def test_labels_never_roundtrip_through_text(self):
        row=fixed_features([77,1],[100,200,1],5)
        self.assertEqual(row['labels'],[100,200,1])
        self.assertEqual(row['attention_mask'],[1,1,0,0,0])

    def test_labels_require_eos(self):
        with self.assertRaises(ValueError):fixed_features([1],[100,200])

    def test_labels_reject_pad(self):
        with self.assertRaises(ValueError):fixed_features([1],[100,0,1])

    def test_finite_stream_order(self):
        rows=[fixed_features([x,1],[100,200,1]) for x in [77,66,88]]
        dataset=OrderedExamples(rows)
        self.assertEqual([r['input_ids'][0] for r in dataset],[77,66,88])
        self.assertEqual(dataset.observed,[0,1,2])


class RealMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.content=load(DATA/'content.tokens.json')
        cls.other=load(DATA/'shuffled.tokens.json')

    def test_all_identity_roundtrips(self):
        tree=CatalogConstraint(self.content,None)
        for doc,tokens in self.content.items():
            self.assertEqual(tree.tree.get(tokens),[doc])
            self.assertEqual(len(tokens),5)

    def test_complete_mapping_multiset(self):
        self.assertEqual(sorted(map(tuple,self.content.values())),sorted(map(tuple,self.other.values())))

    def test_same_lengths_for_every_document(self):
        self.assertEqual(set(self.content),set(self.other))
        self.assertTrue(all(len(self.content[d])==len(self.other[d]) for d in self.content))

    def test_all_actual_prefixes_legal(self):
        tree=CatalogConstraint(self.content,None);tree.seen=[set()]
        for tokens in self.content.values():
            for end,token in enumerate(tokens):
                self.assertIn(token,tree.allowed(0,torch.tensor([0]+tokens[:end])))


if __name__=='__main__':unittest.main()
