"""CPU-only checks for actual preference semantics and numerical explanations."""
import concurrent.futures
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
import numpy as np
from scipy.sparse import csr_matrix
from gsearch.visitor_profile import Preferences,PreferenceConflict,PersonalModel
from gsearch.personal_workbench import FeedbackRequest,ResetRequest,RunRequest


class PreferenceTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.path=Path(self.folder.name)/'prefs.sqlite'
        self.store=Preferences(self.path)

    def tearDown(self):
        assert Path(self.folder.name).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
        self.folder.cleanup()

    def test_persistence_and_isolation(self):
        self.store.change('a',0,'paper','like')
        self.assertEqual(Preferences(self.path).get('a'),{'revision':1,'items':{'paper':'like'}})
        self.assertEqual(self.store.get('b')['items'],{})
        self.store.change('b',0,None,'reset')
        self.assertEqual(self.store.get('a')['revision'],1)

    def test_switch_and_undo(self):
        self.store.change('a',0,'paper','like')
        self.store.change('a',1,'paper','hide')
        self.assertEqual(self.store.get('a')['items'],{'paper':'hide'})
        self.store.change('a',2,'paper','none')
        self.assertEqual(self.store.get('a')['items'],{})

    def test_conflicting_writers(self):
        def write(value):
            try:self.store.change('a',0,'paper',value);return 'ok'
            except PreferenceConflict:return 'conflict'
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(pool.map(write,['like','hide']),['ok','conflict'])
        self.assertEqual(self.store.get('a')['revision'],1)

    def test_capacity_and_reset(self):
        for i in range(500):self.store.change('a',i,str(i),'like')
        with self.assertRaises(ValueError):self.store.change('a',500,'501','hide')
        self.store.change('a',500,'0','hide')
        self.assertEqual(self.store.change('a',501,None,'reset'),{'revision':502,'items':{}})

    def test_request_rejections(self):
        for body in [{'doc_id':'../x','value':'like','revision':0},{'doc_id':'2410.02543','value':'like','revision':True},
                     {'doc_id':'2410.02543','value':'like','revision':0,'owner':'someone'}]:
            with self.assertRaises(ValueError):FeedbackRequest(**body)
        with self.assertRaises(ValueError):ResetRequest(revision=-1)
        with self.assertRaises(ValueError):RunRequest(thread_id='bad',profile='personal')


class NumericalTests(unittest.TestCase):
    def model(self,items):
        from datetime import datetime,timezone
        base=SimpleNamespace(catalog=['a','b','c','d'],position={'a':0,'b':1,'c':2,'d':3},
            by_id={d:{'doc_id':d,'title':d} for d in 'abcd'},cutoff=datetime(2020,1,1,tzinfo=timezone.utc),
            available=np.zeros(4),documents=csr_matrix([[1.,0,0],[0,1.,0],[.6,.8,0],[0,0,0]]),
            features=np.array(['alpha','beta','gamma']),popularity=np.array([1.,2.,3.,4.]),
            valid=lambda d:True,paper=lambda d:{'doc_id':d,'title':d})
        return PersonalModel(base,{'revision':7,'items':items})

    def test_multi_like_contributions(self):
        m=self.model({'a':'like','b':'like'})
        r=m.recommend('visitor','2025-02-23T00:00:00+00:00','content',3,0)
        self.assertEqual([x['doc_id'] for x in r],['c','d'])
        e=r[0]['explanation']
        self.assertAlmostEqual(r[0]['score'],1.4/np.sqrt(2))
        self.assertAlmostEqual(e['all_term_contribution_sum'],e['cosine'])
        self.assertAlmostEqual(e['all_anchor_contribution_sum'],e['cosine'])
        self.assertAlmostEqual(sum(x['score_contribution'] for x in e['anchors']),e['cosine'])
        self.assertEqual(r[1]['explanation']['anchors'],[])

    def test_negative_only_fallback_and_time(self):
        m=self.model({'d':'hide'})
        m.available[2]=9999999999.
        r=m.recommend('visitor','2025-02-23T00:00:00+00:00','content',3,0)
        self.assertEqual([p['doc_id'] for p in r],['b','a'])
        self.assertEqual(r[0]['explanation']['kind'],'popularity_fallback')

    def test_zero_vector_fallback(self):
        m=self.model({'d':'like'})
        self.assertEqual(m.user2row,{})
        self.assertEqual(m.recommend('visitor','2025-02-23T00:00:00+00:00','content',3,0)[0]['doc_id'],'c')


if __name__=='__main__':unittest.main()
