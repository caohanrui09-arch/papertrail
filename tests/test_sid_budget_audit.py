from collections import Counter
import unittest
from gsearch.sid_budget_audit import exposure,transition,weighted_change,select_case,frequency_bin,concentration,output_summary


class BudgetAuditBoundaries(unittest.TestCase):
    def setUp(self):
        self.items={'a':{'pilot_label_count':1,'full_pool_target_count':5,'group':'pilot_target_seen'},
                    'b':{'pilot_label_count':0,'full_pool_target_count':5,'group':'pool_target_not_selected_in_pilot'},
                    'c':{'pilot_label_count':0,'full_pool_target_count':0,'group':'no_source_train_like'}}

    def test_first1024_precedence(self):self.assertEqual(exposure('a',self.items,Counter(a=8)),'labelled_first1024')
    def test_new_label_not_old_history(self):self.assertEqual(exposure('b',self.items,Counter(b=1)),'newly_labelled_1025_4096')
    def test_pool_not_drawn_not_source_cold(self):self.assertEqual(exposure('b',self.items,Counter()),'pool_target_still_unselected')
    def test_source_cold_distinct_from_outside(self):
        self.assertEqual(exposure('c',self.items,Counter()),'no_source_train_like')
        self.assertEqual(exposure('x',self.items,Counter()),'outside_catalog')
    def test_transition_partition(self):
        for ranks,expected in [((None,None),'both_miss'),((None,10),'new_hit'),((1,None),'lost_hit'),
                               ((10,1),'retained_up'),((1,10),'retained_down'),((4,4),'retained_same')]:
            self.assertEqual(transition(*ranks),expected)
    def test_illegal_rank(self):
        for value in [0,11,True,1.1]:
            with self.assertRaises(ValueError):transition(value,None)
    def test_full_user_macro_weight_not_event_micro(self):
        counts=Counter(u=3,v=1)
        self.assertAlmostEqual(weighted_change('u',[],['a'],'a',counts)['ndcg'],1/6)
        self.assertAlmostEqual(weighted_change('v',[],['a'],'a',counts)['ndcg'],1/2)
    def test_loss_signed_and_rank_gain_counts(self):
        counts=Counter(u=1)
        self.assertLess(weighted_change('u',['a'],[],'a',counts)['ndcg'],0)
        self.assertGreater(weighted_change('u',['x','a'],['a','x'],'a',counts)['ndcg'],0)
        self.assertEqual(weighted_change('u',['x','a'],['a','x'],'a',counts)['recall'],0)
    def test_case_selection_order_invariant(self):
        selected={}
        for qid in ['z','a','m']:select_case(selected,'group',{'qid':qid})
        self.assertEqual(selected['group']['qid'],'a')
    def test_frequency_edges(self):
        self.assertEqual([frequency_bin(n) for n in [0,1,4,5,19,20]],['zero','1to4','1to4','5to19','5to19','20plus'])
    def test_positive_share_not_divided_by_net(self):
        rows=[{'user_key':'u','target_doc_id':'a','weighted_delta':{'ndcg':.2},'transition':'new_hit'},
              {'user_key':'v','target_doc_id':'b','weighted_delta':{'ndcg':-.19},'transition':'lost_hit'}]
        result=concentration(rows)
        self.assertEqual(result['top1_user_share_of_gross_positive'],1)
        self.assertAlmostEqual(result['gross_positive_ndcg'],.2)
    def test_output_uses_each_profile_once(self):
        raw={'u':{'fallback':False,'doc_ids':['a']},'v':{'fallback':True,'doc_ids':['b']}}
        result=output_summary(raw,{'a':[2,3,4,5,1],'b':[6,7,8,9,1]},
                              {'a':{'source_train_likes':20}},Counter(a=1))
        self.assertEqual(result['context_users'],1)
        self.assertEqual(result['unique_papers'],1)
        self.assertEqual(result['source_likes_slot_mean'],20)


if __name__=='__main__':unittest.main()
