"""Regression for original failures; no research relevance labels invented."""
import json
from types import SimpleNamespace
import unittest
from gsearch.state_constraints import ActionState,parsed_calls


class StateConstraintTests(unittest.TestCase):
    def state(self,intent='search'):
        return ActionState({'intent':intent})

    def result(self,doc):return {'doc_id':doc,'quotes':[{'quote_index':0,'text':'original fixture'}]}

    def test_null_and_bounds_rejected_without_consuming_attempts(self):
        # Stage82-B: a rejected proposal no longer eats one of the six served actions.
        state=self.state()
        for k in (None,True,0,4):
            with self.assertRaises(ValueError):state.validate('search_papers',{'query':'x','k':k})
        state.charge([{'name':'search_papers','arguments':{'query':'x','k':None}}],'schema rejected null')
        self.assertEqual(state.rejected,1);self.assertEqual(state.charged,0)
        self.assertEqual(state.retrieval_charges,0)
        self.assertFalse(state.retrieved)
        state.validate('search_papers',{'query':'x','k':3})

    def test_duplicate_retrieval_read_and_unread_final_rejected(self):
        state=self.state()
        state.observe('search_papers',{'papers':[{'doc_id':'a'},{'doc_id':'b'}]})
        self.assertNotIn('search_papers',state.legal())
        with self.assertRaises(ValueError):state.validate('search_papers',{'query':'x','k':3})
        with self.assertRaises(ValueError):state.validate('finalize',{'citations':[{'doc_id':'a','quote_index':0}]})
        state.observe('read_paper',self.result('a'))
        with self.assertRaises(ValueError):state.validate('read_paper',{'doc_id':'a'})
        state.validate('finalize',{'citations':[{'doc_id':'a','quote_index':0}]})
        self.assertEqual(state.readable(),['b'])

    def test_mixed_allows_both_orders_but_preserves_last_read(self):
        state=self.state('mixed')
        self.assertEqual(set(state.legal()),{'search_papers','recommend_papers'})
        state.observe('recommend_papers',{'papers':[{'doc_id':'r'},{'doc_id':'r2'}]})
        state.observe('read_paper',self.result('r'))
        self.assertEqual(state.readable(),[])
        state.observe('search_papers',{'papers':[{'doc_id':'s'}]})
        self.assertEqual(state.readable(),['s'])
        state.observe('read_paper',self.result('s'))
        state.validate('finalize',{'citations':[{'doc_id':'s','quote_index':0},{'doc_id':'r','quote_index':0}]})

    def test_empty_and_no_automatic_finalize(self):
        state=self.state('empty')
        self.assertNotIn('final_answer',state.legal())
        state.observe('search_papers',{'papers':[]})
        self.assertEqual(state.legal(),['final_answer'])
        self.assertFalse(state.finished)
        state.validate('finalize',{'citations':[]})
        self.assertFalse(state.finished)
        state.observe('finalize',{'citations':[]})
        self.assertEqual(state.legal(),[])

    def test_rejections_do_not_consume_attempts_but_served_actions_still_do(self):
        # Stage82-B changes the accounting on purpose: rejections are free and bounded
        # by the step limit, while six proposals that reached the server still end the run.
        state=self.state()
        for _ in range(7):state.charge([{'name':'search_papers','arguments':{'k':None}}],'invalid')
        self.assertEqual(state.rejected,7);self.assertEqual(state.charged,0)
        self.assertEqual(len(state.events),7)
        self.assertFalse(state.events[-1]['charged']);self.assertEqual(state.events[-1]['rejected_total'],7)
        for _ in range(6):
            state.wire.append({'name':'search_papers','arguments':{},'sent_to_server':True})
            state.charge([{'name':'search_papers','arguments':{'query':'x','k':3}}],None)
        self.assertEqual(state.charged,6);self.assertEqual(state.legal(),[])

    def test_native_schema_rejects_null_without_executing(self):
        from smolagents import ToolCallingAgent
        from smolagents.tools import validate_tool_arguments
        from smolagents.models import get_tool_json_schema
        from gsearch.constrained_agent import tools_for
        class Client:
            def call(self,*args,**kwargs):raise AssertionError('Schema checks must not execute any tool')
        tools=tools_for(Client());table={t.name:t for t in tools}
        with self.assertRaises(TypeError):validate_tool_arguments(table['search_papers'],{'query':'x','k':None})
        with self.assertRaises(ValueError):validate_tool_arguments(table['search_papers'],{'query':'x'})
        with self.assertRaises(TypeError):validate_tool_arguments(table['search_papers'],{'query':'x','k':True})
        validate_tool_arguments(table['search_papers'],{'query':'x','k':3})
        self.assertIn('k',get_tool_json_schema(table['search_papers'])['function']['parameters']['required'])

    def test_parse_failed_native_dispatch_still_accounts_proposal(self):
        call=SimpleNamespace(function=SimpleNamespace(name='read_paper',arguments={'doc_id':'a'}))
        step=SimpleNamespace(tool_calls=None,model_output_message=SimpleNamespace(tool_calls=[call]))
        self.assertEqual(parsed_calls(step),[{'name':'read_paper','arguments':{'doc_id':'a'}}])

    def test_native_loop_masks_repeats_and_bills_schema_rejections(self):
        from unittest.mock import patch
        from smolagents.models import Model,ChatMessage
        from smolagents.monitoring import TokenUsage
        from gsearch.budget_model import GenerationMeter
        from gsearch.constrained_agent import run
        from gsearch.unified_session import UnifiedSession
        from gsearch.unified_search import AsOfBM25
        from tests.test_unified import Model as FixtureCorpus
        calls=[('recommend_papers',{'k':None}),('recommend_papers',{'k':3}),
            ('recommend_papers',{'k':3}),('read_paper',{'doc_id':'c'}),
            ('final_answer',{'answer':{'citations':[{'doc_id':'c','quote_index':0}]}})]
        class Scripted(Model):
            def __init__(self):super().__init__(model_id='unit-script-not-a-real-LLM');self.index=0
            def reset_budget(self,budget):self.meter=GenerationMeter(budget)
            def generate(self,messages,**kwargs):
                self.meter.reserve_input(1);self.meter.record_output(1)
                name,args=calls[self.index];self.index+=1
                return ChatMessage(role='assistant',content=json.dumps({'name':name,'arguments':args}),token_usage=TokenUsage(input_tokens=1,output_tokens=1))
        corpus=FixtureCorpus();search=AsOfBM25(corpus);self.addCleanup(search.close)
        session=UnifiedSession(corpus,search,'u','2024-06-01T00:00:00Z')
        def transport(method,path,data=None,port=8766):
            if path=='/sessions':return 200,{'session_id':'fixture'}
            if method=='GET':return 200,session.snapshot()
            if method=='DELETE':return 200,{'deleted':True}
            result=session.invoke(data['name'],data['arguments'])
            return (400,{'detail':result['error']}) if 'error' in result else (200,result)
        task={'id':'unit','intent':'recommend','query':'','instruction':'unit fixture only',
            'user_id':'u','at':'2024-06-01T00:00:00Z'}
        with patch('gsearch.unified_agent.request',side_effect=transport):result=run(task,Scripted())
        self.assertTrue(result['completed_protocol'])
        self.assertEqual(result['metadata']['charged_application_attempts'],3)
        events=result['metadata']['proposal_events']
        self.assertEqual(len(events),5)
        self.assertEqual(sum(1 for event in events if not event['charged']),2)
        self.assertEqual(len(result['trace']['trace']),3)
        self.assertEqual([t['tool'] for t in result['trace']['trace']],['recommend_papers','read_paper','finalize'])
        self.assertTrue(result['metadata']['proposal_events'][0]['error'])
        self.assertTrue(result['metadata']['proposal_events'][2]['error'])


if __name__=='__main__':unittest.main()
