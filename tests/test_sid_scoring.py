import unittest

from gsearch.sid_scoring import accelerated_evaluate
from gsearch.supervision_evaluation import evaluate


class EquivalentChecks(unittest.TestCase):
    def setUp(self):
        self.catalog={f'd{i}':{'available_at':'2020-01-01T00:00:00+00:00'} for i in range(12)}
        self.profiles={'warm':{'eligible_train_positive_count':3,'seen_doc_ids':['d0']},
                       'cold':{'eligible_train_positive_count':0,'seen_doc_ids':['d0']}}
        self.popularity={d:12-i for i,d in enumerate(self.catalog)}
        self.labels=[{'qid':str(i),'user_key':user,'target_doc_id':target,'at':'2024-01-01T00:00:00+00:00',
                      'user_group':'cold' if user!='warm' else 'sparse','item_group':'trainliked'}
                     for i,(user,target) in enumerate([('warm','d2'),('cold','d4'),('new','outside'),('cold','d1'),('warm','d3')])]
        self.predictions=[{'qid':r['qid'],'doc_ids':['d1','d2'] if r['user_key']=='warm' else
                          ([f'd{i}' for i in range(1,11)] if r['user_key']=='cold' else [f'd{i}' for i in range(10)])}
                         for r in self.labels]

    def assert_same(self,predictions):
        args=(self.labels,predictions,self.profiles,self.catalog,10,self.popularity)
        self.assertEqual(evaluate(*args),accelerated_evaluate(*args))

    def assert_both_reject(self,predictions):
        for function in [evaluate,accelerated_evaluate]:
            with self.assertRaises(ValueError):function(self.labels,predictions,self.profiles,self.catalog,10,self.popularity)

    def test_full_metrics_and_group_equality(self):self.assert_same(self.predictions)

    def test_empty_failure_lists(self):self.assert_same([{'qid':r['qid'],'doc_ids':[]} for r in self.labels])

    def test_duplicate_seen_invalid_slots(self):
        rows=[dict(r) for r in self.predictions]
        for row in rows:
            if row['qid'] in ['0','4']:row['doc_ids']=['d0','d2','d2','outside',None]
        self.assert_same(rows)

    def test_inconsistent_user_rejected(self):
        rows=[dict(r) for r in self.predictions];rows[4]['doc_ids']=['d4']
        self.assert_both_reject(rows)

    def test_wrong_cold_fallback_rejected(self):
        rows=[dict(r) for r in self.predictions]
        for row in rows:
            if row['qid'] in ['1','3']:row['doc_ids']=['d2','d1']
        self.assert_both_reject(rows)

    def test_missing_event_rejected(self):self.assert_both_reject(self.predictions[:-1])

    def test_duplicate_event_rejected(self):self.assert_both_reject(self.predictions+[self.predictions[0]])

    def test_unknown_event_rejected(self):self.assert_both_reject(self.predictions+[{'qid':'unknown','doc_ids':[]}])

    def test_extra_schema_rejected(self):
        rows=[dict(r) for r in self.predictions];rows[0]['extra']=True
        self.assert_both_reject(rows)

    def test_reordered_events_preserve_results(self):self.assert_same(self.predictions[::-1])


if __name__=='__main__':unittest.main()
