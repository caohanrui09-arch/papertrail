"""Explicit-version/as-of boundaries, unseen-item scores, and future-text isolation."""
import importlib.util
from pathlib import Path
import unittest
import numpy as np

if importlib.util.find_spec('pandas') is None or not Path('.cache/stage11/deps/sklearn').exists():
    raise unittest.SkipTest('Use existing stage6 runtime and stage11 isolated content dependencies')
import pandas as pd
from gsearch.expansion_data import available_at
from gsearch.expansion_recommendation import ExpansionRecommender,signature

def fixture(future_text: str='quantum photon futureonlyword') -> ExpansionRecommender:
    ids=['2401.00001','2401.00002','2401.00003','2404.00004','2401.00005']
    texts=['quantum photon optical','biology protein cell','biology protein assay',future_text,'quantum photon experiment']
    rows=[]
    for i,(d,text) in enumerate(zip(ids,texts)):
        published='2024-04-01T12:00:00Z' if i==3 else '2024-01-01T12:00:00Z'
        rows.append({'doc_id':d,'title':text,'abstract':text,'version':1,'cohort':'warm' if i<3 else 'new_cold' if i==3 else 'old_cold',
             'published_at':published,'available_at':available_at(published).isoformat(),'source_url':'https://arxiv.org/abs/'+d+'v1'})
    train=pd.DataFrame([('alice',ids[0],1),('alice',ids[4],-1),('bob',ids[1],1),('bob',ids[2],1),('carol',ids[0],1),('carol',ids[2],1)],columns=['user_id','arxiv_id','rating'])
    return ExpansionRecommender(train,rows,'2024-03-01T00:00:00Z',params={'ngram_range':[1,2],'min_df':1,'norm':'l2'})

class ExpansionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:cls.model=fixture()

    def test_asof_shared_mask_and_no_future_read(self) -> None:
        m=self.model
        for method in ('popular','sar','content','hybrid'):
            hits=m.recommend('alice','2024-03-10',method)
            self.assertFalse({r['doc_id'] for r in hits}&{'2401.00001','2401.00005','2404.00004'})
        with self.assertRaises(ValueError):m.read('2404.00004','2024-03-10')
        with self.assertRaises(ValueError):m.recommend('alice','2024-02-01')

    def test_item_cold_zero_cf_but_content_scores_and_admits_after_time(self) -> None:
        m=self.model;i=m.position['2404.00004']
        self.assertEqual(m.sar_scores('alice')[i],0)
        self.assertEqual(m.popularity[i],0)
        self.assertGreater(m.content_scores('alice')[i],0)
        self.assertEqual(m.recommend('alice','2024-04-10','content')[0]['doc_id'],'2404.00004')
        self.assertNotIn('futureonlyword',m.vectorizer.vocabulary_)

    def test_future_text_changes_cannot_change_prior_recommendations_or_fit(self) -> None:
        old=self.model;changed=fixture('biology futurepoisonword protein protein')
        self.assertEqual(old.vectorizer.vocabulary_,changed.vectorizer.vocabulary_)
        np.testing.assert_array_equal(old.vectorizer.idf_,changed.vectorizer.idf_)
        np.testing.assert_array_equal(old.profiles.toarray(),changed.profiles.toarray())
        for mode in ('popular','sar','content','hybrid'):
            self.assertEqual(old.recommend('alice','2024-03-10',mode),changed.recommend('alice','2024-03-10',mode))

    def test_cold_user_and_endpoints_are_exact(self) -> None:
        m=self.model;at='2024-04-10'
        for mode in ('sar','content','hybrid'):
            self.assertEqual([r['doc_id'] for r in m.recommend('new',at,mode)],
                             [r['doc_id'] for r in m.recommend('new',at,'popular')])
        for user in ('alice','bob','new'):
            np.testing.assert_array_equal(m.rank_indices(user,at,'hybrid',alpha=0),m.rank_indices(user,at,'content'))
            np.testing.assert_array_equal(m.rank_indices(user,at,'hybrid',alpha=1),m.rank_indices(user,at,'sar'))

    def test_availability_proxy_is_day_end_plus_24h(self) -> None:
        self.assertEqual(available_at('2024-04-01T23:59:59Z').isoformat(),'2024-04-03T00:00:00+00:00')
        self.assertEqual(available_at('2024-04-02T07:59:59+08:00').isoformat(),'2024-04-03T00:00:00+00:00')

    def test_inference_does_not_mutate_frozen_model_signature(self) -> None:
        before=signature(self.model)
        for mode in ('popular','sar','content','hybrid'):
            self.model.recommend('alice','2024-04-10',mode)
        self.assertEqual(before,signature(self.model))

    def test_offline_batch_original_scores_match_uncached_single_requests(self) -> None:
        users=['alice','bob','new']
        cf,text=self.model.batch_components(users)
        for j,user in enumerate(users):
            a,b=self.model.components(user)
            np.testing.assert_allclose(cf[j],a,rtol=1e-14,atol=1e-14)
            np.testing.assert_allclose(text[j],b,rtol=1e-14,atol=1e-14)
            for mode in ('popular','sar','content','hybrid'):
                np.testing.assert_array_equal(self.model.rank_indices(user,'2024-04-10',mode),
                   self.model.rank_indices(user,'2024-04-10',mode,components=(cf[j],text[j])))

    def test_genuine_tools_read_and_reparse_cached_official_v1(self) -> None:
        from gsearch.catalog_audit import read
        from gsearch.expansion_discovery import ExpansionSession,make_tools
        import copy
        paths=sorted(Path('.cache/stage13/batches').glob('00000-*.json'))
        if not paths:self.skipTest('Source-only official probe cache absent')
        from gsearch.catalog_audit import stamp
        raw=[r for r in read(paths[0])['records'] if available_at(r['published_at'])<stamp('2024-10-27T18:52:32Z')][:3]
        records=[]
        for i,r in enumerate(raw):
            item=copy.deepcopy(r)
            item.update(cohort='warm' if i<2 else 'old_cold',available_at=available_at(r['published_at']).isoformat(),
                        version_key='arxiv:'+r['doc_id']+'v1',time_assumption='explicit test of source transport only')
            records.append(item)
        train=pd.DataFrame([('a',records[0]['doc_id'],1),('b',records[1]['doc_id'],1)],columns=['user_id','arxiv_id','rating'])
        m=ExpansionRecommender(train,records,'2024-10-27T18:52:32Z',params={'ngram_range':[1,2],'min_df':1,'norm':'l2'})
        session=ExpansionSession(m,'a','2025-02-23T05:28:26Z')
        tools={t.name:t for t in make_tools(session)}
        with self.assertRaises(ValueError):session.read(records[1]['doc_id'])
        papers=tools['recommend_papers'](k=2)['papers']
        result=tools['read_paper'](doc_id=papers[0]['doc_id'])
        self.assertTrue(result['source_verified']);self.assertEqual(result['version'],1)
        self.assertFalse(result['semantic_stance_verified'])
        m.by_id[papers[0]['doc_id']]['abstract']='tampered summary'
        with self.assertRaises(ValueError):m.read(papers[0]['doc_id'],session.at)

    def test_real_replay_counts_unavailable_gold_and_keeps_future_events(self) -> None:
        import tempfile
        from unittest.mock import patch
        from gsearch import benchmark_expansion as benchmark
        from gsearch.expansion_data import save,read
        ids=['2401.00001','2401.00002','2401.00003','2404.00004','2401.00005']
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);data=base/'data';reports=base/'reports';original=base/'original'
            for p in (data,reports,original):p.mkdir()
            train=pd.DataFrame([('alice',ids[0],1),('alice',ids[4],-1),('bob',ids[1],1),('bob',ids[2],1),('carol',ids[0],1),('carol',ids[2],1)],columns=['user_id','arxiv_id','rating'])
            train.to_csv(original/'train.csv',index=False)
            pd.DataFrame([('alice',ids[3],1,'2024-03-10T00:00:00Z'),('bob',ids[3],1,'2024-04-10T00:00:00Z')],
                         columns=['user_id','arxiv_id','rating','time']).to_csv(original/'tuning.csv',index=False)
            (original/'dev.csv').write_bytes((original/'tuning.csv').read_bytes())
            save(reports/'resource-5.json',{'model_signature':signature(self.model)})
            save(reports/'evaluation-plan.json',{'fixture':True})
            save(reports/'locked-before-dev.json',{'tiers':{'5':{'alpha':.5}}})
            with patch.object(benchmark,'ROOT',reports),patch.object(benchmark,'DATA',data),patch.object(benchmark,'ORIGINAL',original),\
                 patch.object(benchmark,'load',return_value=self.model),patch.object(benchmark,'check_plan',return_value={}):
                benchmark.evaluate('tuning',5)
                benchmark.evaluate('dev',5)
            result=read(reports/'5-content-tuning.json')
            self.assertEqual(result['summary']['positive_events'],2)
            self.assertAlmostEqual(result['summary']['recall@10'],.5)
            self.assertAlmostEqual(result['summary']['ndcg@10'],.25)
            self.assertAlmostEqual(result['summary']['eligible_gold_event_fraction'],.5)
            events=read(data/'5-tuning-events.json')
            self.assertFalse(events[0]['available_gold']);self.assertTrue(events[1]['available_gold'])
            latency=read(reports/'5-latency-dev.json')
            self.assertEqual(latency['requests'],2);self.assertFalse(latency['component_score_cache'])

if __name__=='__main__':unittest.main()
