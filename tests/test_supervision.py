"""Synthetic boundary fixtures, separate from all real user/model evaluation."""
import io
import unittest

import pandas as pd

from gsearch.supervision import build_train, score_rows
from gsearch.supervision_evaluation import evaluate, locked_run


class SupervisionTests(unittest.TestCase):
    def setUp(self):
        self.catalog={d:{'available_at':'2024-01-01T00:00:00+00:00','version_key':'arxiv:'+d+'v1'} for d in ['2401.00001','2401.00002','2401.00003']}
        self.profiles={'u':{'seen_doc_ids':['2401.00003'],'eligible_train_positive_count':2}}
        self.labels=[{'qid':'a','user_key':'u','target_doc_id':'2401.00002','at':'2024-02-01T00:00:00+00:00','user_group':'sparse','item_group':'trainliked'}]

    def source(self,rows):
        return pd.DataFrame([{'user_key':'u','doc_id':d,'rating':rating,'at':pd.Timestamp(t),'event_id':str(i),'source_row':i+2} for i,(d,rating,t) in enumerate(rows)])

    def test_strict_equal_time_no_cross_supervision(self):
        rows=[('2401.00001',1,'2024-01-02T00:00:00Z'),('2401.00002',1,'2024-01-02T00:00:00Z'),('2401.00003',1,'2024-01-03T00:00:00Z')]
        samples,feedback=io.StringIO(),io.StringIO()
        profiles,counts,_=build_train(self.source(rows),self.catalog,20,samples,feedback)
        import json
        records=[json.loads(x) for x in samples.getvalue().splitlines()]
        self.assertEqual(counts['supervised_samples'],1)
        self.assertEqual(records[0]['history_doc_ids'],['2401.00001','2401.00002'])

    def test_negative_seen_but_never_positive_history(self):
        samples,feedback=io.StringIO(),io.StringIO()
        p,_,_=build_train(self.source([('2401.00001',-1,'2024-01-02T00:00:00Z'),('2401.00002',1,'2024-01-03T00:00:00Z')]),self.catalog,20,samples,feedback)
        self.assertIn('2401.00001',p['u']['seen_doc_ids'])
        self.assertNotIn('2401.00001',p['u']['history_doc_ids'])

    def test_before_availability_not_supervised_or_context(self):
        s,f=io.StringIO(),io.StringIO()
        p,c,_=build_train(self.source([('2401.00001',1,'2023-12-31T00:00:00Z')]),self.catalog,20,s,f)
        self.assertEqual(c['positive_before_availability_proxy'],1)
        self.assertEqual(p['u']['history_doc_ids'],[])
        self.assertEqual(samples:=s.getvalue(),'')

    def test_history_window_is_bounded(self):
        catalog={f'2401.{i:05d}':{'available_at':'2024-01-01T00:00:00Z','version_key':'v1'} for i in range(1,5)}
        rows=[(d,1,f'2024-01-0{i+2}T00:00:00Z') for i,d in enumerate(catalog)]
        s,f=io.StringIO(),io.StringIO();p,c,_=build_train(self.source(rows),catalog,2,s,f)
        self.assertEqual(p['u']['history_doc_ids'],list(catalog)[-2:])

    def test_outside_target_stays_miss(self):
        label=self.labels[0]|{'target_doc_id':'2501.99999','item_group':'outside_catalog'}
        r=score_rows([label],[{'qid':'a','doc_ids':['2501.99999']}],self.profiles,self.catalog)
        self.assertEqual(r['events'],1);self.assertEqual(r['user_macro']['recall@10'],0)

    def test_seen_output_consumes_rank(self):
        r=score_rows(self.labels,[{'qid':'a','doc_ids':['2401.00003','2401.00002']}],self.profiles,self.catalog)
        self.assertEqual(r['user_macro']['mrr@10'],.5)

    def test_duplicate_output_consumes_rank(self):
        r=score_rows(self.labels,[{'qid':'a','doc_ids':['2401.00001','2401.00001','2401.00002']}],self.profiles,self.catalog)
        self.assertAlmostEqual(r['user_macro']['mrr@10'],1/3)
        self.assertEqual(r['duplicate_slot_rate'],.1)

    def test_missing_qid_rejected(self):
        with self.assertRaisesRegex(ValueError,'Missing'):score_rows(self.labels,[],self.profiles,self.catalog)

    def test_extra_qid_rejected(self):
        with self.assertRaises(ValueError):score_rows(self.labels,[{'qid':'x','doc_ids':[]}],self.profiles,self.catalog)

    def test_duplicate_qid_rejected(self):
        with self.assertRaises(ValueError):score_rows(self.labels,[{'qid':'a','doc_ids':[]}]*2,self.profiles,self.catalog)

    def test_empty_output_explicit_miss(self):
        r=score_rows(self.labels,[{'qid':'a','doc_ids':[]}],self.profiles,self.catalog)
        self.assertEqual(r['user_macro']['ndcg@10'],0)

    def test_fixed_profile_cannot_change_predictions(self):
        labels=self.labels+[self.labels[0]|{'qid':'b'}]
        with self.assertRaisesRegex(ValueError,'Fixed profile'):
            evaluate(labels,[{'qid':'a','doc_ids':[]},{'qid':'b','doc_ids':['2401.00002']}],self.profiles,self.catalog)

    def test_user_macro_not_event_micro(self):
        labels=self.labels+[self.labels[0]|{'qid':'b'},self.labels[0]|{'qid':'c','user_key':'v','user_group':'cold'}]
        p=[{'qid':q,'doc_ids':['2401.00002'] if q=='c' else []} for q in ['a','b','c']]
        r=evaluate(labels,p,self.profiles,self.catalog)
        self.assertEqual(r['user_macro']['recall@10'],.5)
        self.assertAlmostEqual(r['event_micro']['recall@10'],1/3)

    def test_new_user_distinct_from_catalog_cold(self):
        labels=[self.labels[0]|{'user_key':'new','user_group':'cold'}]
        r=evaluate(labels,[{'qid':'a','doc_ids':[]}],self.profiles,self.catalog)
        self.assertEqual(r['source_user_event_counts']['new_to_source_training'],1)

    def test_unfilled_run_template_rejected(self):
        with self.assertRaises(ValueError):locked_run({},'p','c','a')

    def test_noncanonical_prediction_is_not_silently_remapped(self):
        r=score_rows(self.labels,[{'qid':'a','doc_ids':['arxiv:2401.00002v1']}],self.profiles,self.catalog)
        self.assertEqual(r['user_macro']['recall@10'],0)

    def test_zero_context_common_fallback(self):
        labels=[self.labels[0]|{'user_key':'new','user_group':'cold'}]
        with self.assertRaisesRegex(ValueError,'popularity'):
            evaluate(labels,[{'qid':'a','doc_ids':['2401.00002']}],self.profiles,self.catalog,popularity={})

    def test_fallback_preserves_seen_mask_and_ties(self):
        profiles={'u':{'seen_doc_ids':['2401.00003'],'eligible_train_positive_count':0}}
        r=evaluate(self.labels,[{'qid':'a','doc_ids':['2401.00001','2401.00002']}],profiles,self.catalog,popularity={'2401.00003':9})
        self.assertEqual(r['user_macro']['mrr@10'],.5)

    def test_zero_context_explicit_failure_kept(self):
        labels=[self.labels[0]|{'user_key':'new','user_group':'cold'}]
        r=evaluate(labels,[{'qid':'a','doc_ids':[]}],self.profiles,self.catalog,popularity={})
        self.assertEqual(r['events'],1)

    def test_truthy_gates_cannot_replace_locked_inputs(self):
        with self.assertRaises(ValueError):
            locked_run({'resource_preflight_passed':True,'real_tokenizer_and_decode_preflight_passed':True,'frozen_before_training':True},'p','c','a')


if __name__=='__main__':
    unittest.main()
