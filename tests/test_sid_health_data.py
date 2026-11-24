from collections import Counter
import unittest

from gsearch.sid_health_data import same_length_swap,select_profiles,select_prefixes,source_key


class SourceOnlySampling(unittest.TestCase):
    def row(self,user,history):
        return {'user_key':user,'history_doc_ids':history,'eligible_train_positive_count':len(history),'seen_doc_ids':history+['negative']}

    def test_equal_length_permutation_changes_every_history(self):
        rows=[self.row(str(i),[str(i)]) for i in range(6)]
        donors=same_length_swap(rows)
        self.assertEqual(sorted(donors),list(range(6)))
        self.assertTrue(all(i!=j for i,j in enumerate(donors)))
        self.assertTrue(all(rows[i]['history_doc_ids']!=rows[j]['history_doc_ids'] for i,j in enumerate(donors)))

    def test_reject_identical_histories(self):
        with self.assertRaises(ValueError):same_length_swap([self.row('a',['x']),self.row('b',['x'])])

    def test_reject_length_change(self):
        with self.assertRaises(ValueError):same_length_swap([self.row('a',['x']),self.row('b',['x','y'])])

    def test_source_order_does_not_choose_outcomes(self):
        rows=[self.row(str(i),[str(i)]) for i in range(8)]
        first=select_profiles(rows,lengths=(1,),per_length=4)
        second=select_profiles(rows[::-1],lengths=(1,),per_length=4)
        self.assertEqual(first,second)
        self.assertEqual(Counter(tuple(r['original_history_doc_ids']) for r in first),
                         Counter(tuple(r['swapped_history_doc_ids']) for r in first))
        self.assertTrue(all(r['seen_doc_ids'][-1]=='negative' for r in first))

    def test_strict_prefix_selection_separates_exposure(self):
        samples=[{'sample_id':str(i),'target_doc_id':'target'+str(i),'history_doc_ids':['a']*length}
                 for i,length in enumerate([1,20,1,20])]
        selected,counts,pool=select_prefixes(iter(samples),{'0','1'},per_cell=1)
        self.assertEqual(len(selected),4)
        self.assertEqual(Counter(r['exposure_group'] for r in selected),{'pilot':2,'pool_not_pilot':2})
        self.assertEqual(sum(counts.values()),2)
        self.assertEqual(sum(pool.values()),4)

    def test_target_in_history_rejected(self):
        samples=[{'sample_id':str(i),'target_doc_id':'a' if i==0 else 'target','history_doc_ids':['a']*length}
                 for i,length in enumerate([1,20,1,20])]
        with self.assertRaises(ValueError):select_prefixes(iter(samples),{'0','1'},per_cell=1)

    def test_hash_does_not_depend_on_holdout_metadata(self):
        self.assertEqual(source_key('profile','user'),source_key('profile','user'))
        self.assertNotEqual(source_key('profile','user'),source_key('prefix','user'))


if __name__=='__main__':unittest.main()
