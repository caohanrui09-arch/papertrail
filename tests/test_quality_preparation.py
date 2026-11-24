"""Human-label gates and metric boundaries; all labels here are unit fixtures."""
import copy
import math
from pathlib import Path
import unittest

from gsearch.quality_protocol import (judgments, confirmations, coverage,
    import_label_studio, csv_text, JUDGMENT_FIELDS)
from gsearch.human_quality import evaluate, native_scores, sheet_rows


class QualityPreparationTests(unittest.TestCase):
    def setUp(self):
        self.queries=[{'query_id':'q','request':'unit fixture request','query_origin':'assistant_draft','split':'tuning'}]
        self.mapping={'a':{'query_id':'q','doc_id':'d','split':'tuning'}}
        self.runs={method:{'q':['d']} for method in ('bm25','query_tfidf','personalized_query_tfidf')}
        self.blank={name:'' for name in JUDGMENT_FIELDS};self.blank['annotation_id']='a'
        self.human={**self.blank,'grade':'2','annotator_id':'unit-fixture-not-a-real-annotator','judgment_origin':'human',
            'judged_at':'2026-10-28T00:00:00Z','rationale':'synthetic unit test only'}
        self.review={'query_id':'q','request':'unit fixture request','query_origin':'assistant_draft',
            'confirmed':'yes','reviewer_id':'unit-fixture','reviewed_at':'2026-10-28T00:00:00Z','note':'test only'}

    def test_blank_is_unjudged_and_quality_blocked(self):
        labels=judgments([self.blank],self.mapping)
        self.assertEqual(labels,{})
        state=coverage(self.queries,self.mapping,self.runs,labels,set())
        self.assertEqual(state['human_judged_pairs'],0)
        self.assertIsNone(state['ndcg_at10']);self.assertIsNone(state['mrr_at10'])
        with self.assertRaises(ValueError): evaluate(self.queries,self.mapping,self.runs,labels,{'q'},'tuning')
        labels=judgments([self.human],self.mapping)
        with self.assertRaises(ValueError): evaluate(self.queries,self.mapping,self.runs,labels,set(),'tuning')

    def test_source_grade_schema_duplicates_and_time(self):
        for mutation in [{'grade':'3'},{'grade':'0.0'},{'grade':True},{'judgment_origin':'llm'},
            {'annotator_id':''},{'rationale':''},{'judged_at':'2026-10-28'},{'annotation_id':'unknown'}]:
            with self.assertRaises(ValueError): judgments([{**self.human,**mutation}],self.mapping)
        with self.assertRaises(ValueError): judgments([self.human,self.human],self.mapping)
        self.assertEqual(judgments([{**self.human,'grade':'0'}],self.mapping)['a']['grade'],0)

    def test_confirmation_cannot_rewrite_query_origin_or_text(self):
        self.assertEqual(confirmations([self.review],self.queries),{'q'})
        for mutation in [{'request':'edited'},{'query_origin':'human_authored'},{'reviewer_id':''},{'reviewed_at':'2026-10-28'}]:
            with self.assertRaises(ValueError): confirmations([{**self.review,**mutation}],self.queries)

    def test_sheet_metadata_and_csv_formula_safety(self):
        template=[{**self.blank,'request':'original','title':'paper'}]
        full={**template[0],**self.human}
        self.assertEqual(sheet_rows([full],template),[self.human])
        with self.assertRaises(ValueError):sheet_rows([{**full,'title':'edited'}],template)
        for text in ['=SUM(1,2)',' +cmd','-123','@thing']:
            self.assertTrue(csv_text(text).startswith("'"))
        self.assertEqual(csv_text('ordinary abstract'),'ordinary abstract')

    def test_label_studio_requires_explicit_human_declaration(self):
        task={'data':{'annotation_id':'a'},'annotations':[{'created_at':'2026-10-28T00:00:00Z','result':[
            {'from_name':'relevance','to_name':'paper','type':'choices','value':{'choices':['2 高度相关']}},
            {'from_name':'rationale','to_name':'paper','type':'textarea','value':{'text':['unit fixture only']}}]}]}
        with self.assertRaises(ValueError):import_label_studio([task],self.mapping,'unit',False)
        self.assertEqual(import_label_studio([task],self.mapping,'unit-fixture',True)[0]['grade'],'2')
        for modified in [{**task,'predictions':[{}]}, {**task,'annotations':task['annotations']*2},
            {**task,'annotations':[{**task['annotations'][0],'was_cancelled':True}]}]:
            with self.assertRaises(ValueError):import_label_studio([modified],self.mapping,'unit',True)
        self.assertEqual(import_label_studio([{'data':{'annotation_id':'a'}}],self.mapping,'unit',True),[])

    def test_native_metrics_pad_missing_slots_and_include_zero_positive_queries(self):
        from gsearch.content_recommendation import sklearn_runtime
        sklearn_runtime()
        result=native_scores({'q':{'a':2,'b':1}},{'q':['b']})
        expected=1/(3+1/math.log2(3))
        self.assertAlmostEqual(result['pooled_ndcg_at10'],expected,places=10)
        self.assertEqual(result['pooled_mrr_at10'],1.)
        empty=native_scores({'q':{'a':2,'b':1}},{'q':[]})
        self.assertEqual(empty['pooled_ndcg_at10'],0.)
        self.assertEqual(empty['pooled_mrr_at10'],0.)
        zero=native_scores({'q':{'a':0}},{'q':['a']})
        self.assertEqual(zero['pooled_ndcg_at10'],0.)
        self.assertEqual(zero['pooled_queries_with_no_positive_judgment'],1)

    def test_native_tools_default_k_and_explicit_invalid_k(self):
        from gsearch.unified_agent import make_tools
        class Client:
            def __init__(self):self.calls=[]
            def call(self,name,**kwargs):
                self.calls.append((name,kwargs))
                if type(kwargs.get('k')) is not int or kwargs['k']<1:raise ValueError('invalid k')
                return {'papers':[]}
        client=Client();tools={t.name:t for t in make_tools(client)}
        tools['recommend_papers']()
        tools['search_papers'](query='unit query')
        self.assertEqual([c[1]['k'] for c in client.calls],[3,3])
        for k in (None,True,11):
            with self.assertRaises(ValueError):tools['recommend_papers'](k=k)


if __name__=='__main__':unittest.main()
