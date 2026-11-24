"""Prevent cross-agent schema leakage in both strategy execution orders."""
from copy import deepcopy
from types import SimpleNamespace
import unittest


class SchemaIsolationTests(unittest.TestCase):
    def test_two_sessions_preserve_native_final_schema_and_each_other(self):
        from smolagents.default_tools import FinalAnswerTool
        from gsearch.constrained_agent import tools_for
        from gsearch.schema_isolation import IsolatedActionState
        defaults=deepcopy(FinalAnswerTool.inputs)
        class Client:
            def call(self,*args,**kwargs):raise AssertionError('No automatic execution')
        def fixture():
            tools={t.name:t for t in tools_for(Client())};tools['final_answer']=FinalAnswerTool()
            agent=SimpleNamespace(memory=SimpleNamespace(system_prompt=SimpleNamespace(system_prompt='')),system_prompt='fixture',instructions='',tools={})
            return tools,agent
        a,agent_a=fixture();b,agent_b=fixture();ordinary=FinalAnswerTool()
        state_a=IsolatedActionState({'intent':'search'});state_b=IsolatedActionState({'intent':'recommend'})
        state_a.refresh(agent_a,a)
        after_a=deepcopy(a['final_answer'].inputs)
        state_b.observe('recommend_papers',{'papers':[{'doc_id':'other'}]})
        state_b.refresh(agent_b,b)
        self.assertEqual(a['final_answer'].inputs,after_a)
        self.assertEqual(ordinary.inputs,defaults);self.assertEqual(FinalAnswerTool.inputs,defaults)
        self.assertIsNot(a['final_answer'].inputs,FinalAnswerTool.inputs)
        self.assertIsNot(a['final_answer'].inputs,b['final_answer'].inputs)
        self.assertEqual(FinalAnswerTool().inputs,defaults)

    def test_native_default_tool_stays_unrestricted_after_refresh(self):
        from smolagents.default_tools import FinalAnswerTool
        from smolagents.tools import validate_tool_arguments
        from gsearch.constrained_agent import tools_for
        from gsearch.schema_isolation import IsolatedActionState
        ordinary=FinalAnswerTool();before=deepcopy(ordinary.inputs)
        tools={t.name:t for t in tools_for(SimpleNamespace())};tools['final_answer']=FinalAnswerTool()
        agent=SimpleNamespace(memory=SimpleNamespace(system_prompt=SimpleNamespace(system_prompt='')),system_prompt='fixture')
        IsolatedActionState({'intent':'search'}).refresh(agent,tools)
        self.assertEqual(ordinary.inputs,before)
        validate_tool_arguments(ordinary,{'answer':'ordinary baseline string remains legal'})
        self.assertEqual(FinalAnswerTool().inputs,before)


if __name__=='__main__':unittest.main()
