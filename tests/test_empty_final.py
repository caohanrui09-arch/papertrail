"""Stage88-v2: zero-result final answer is an empty object, normalised by the client."""
from unittest.mock import patch
import unittest

from gsearch.constrained_agent import GuardedClient
from gsearch.state_constraints import ActionState


class Tool:
    def __init__(self):
        self.inputs = {'k': {}, 'doc_id': {}, 'answer': {}}


class Agent:
    def __init__(self):
        self.tools = {}
        self.instructions = ''
        self.system_prompt = 'system'
        self.memory = type('M', (), {'system_prompt': type('S', (), {'system_prompt': ''})()})()


def tools():
    return {name: Tool() for name in ('search_papers', 'recommend_papers', 'read_paper', 'final_answer')}


class EmptyFinalSchemaTests(unittest.TestCase):
    def test_refresh_sets_an_empty_object_schema(self):
        state = ActionState({'intent': 'search'})
        state.observe('search_papers', {'papers': []})
        table = tools()
        state.refresh(Agent(), table)
        answer = table['final_answer'].inputs['answer']
        self.assertEqual(answer['properties'], {})
        self.assertEqual(answer['required'], [])
        self.assertFalse(answer['additionalProperties'])

    def test_non_empty_state_keeps_the_citation_schema(self):
        state = ActionState({'intent': 'search'})
        state.observe('search_papers', {'papers': [{'doc_id': 'a'}]})
        table = tools()
        state.refresh(Agent(), table)
        answer = table['final_answer'].inputs['answer']
        self.assertIn('citations', answer['properties'])
        self.assertEqual(answer['properties']['citations']['minItems'], 1)


class EmptyFinalClientTests(unittest.TestCase):
    def client(self, state):
        client = object.__new__(GuardedClient)
        client.controller = state
        client.accepted = None
        client.accepted_input = None
        return client

    def test_empty_object_is_normalised_to_empty_citations(self):
        state = ActionState({'intent': 'search'})
        state.observe('search_papers', {'papers': []})
        client = self.client(state)
        with patch('gsearch.unified_agent.ToolClient.call', return_value={'citations': []}) as mocked:
            out = client.finalize({})
        mocked.assert_called_once_with('finalize', citations=[])
        self.assertEqual(out, {'citations': []})

    def test_empty_object_is_rejected_when_papers_exist(self):
        state = ActionState({'intent': 'search'})
        state.observe('search_papers', {'papers': [{'doc_id': 'a'}]})
        client = self.client(state)
        with self.assertRaises(ValueError):
            client.finalize({})

    def test_fabricated_citations_are_still_rejected_when_empty(self):
        state = ActionState({'intent': 'search'})
        state.observe('search_papers', {'papers': []})
        client = self.client(state)
        with patch('gsearch.unified_agent.ToolClient.call', return_value={'citations': []}) as mocked:
            with self.assertRaises(ValueError):
                client.finalize({'citations': [{'doc_id': 'QZX_PAPER_1', 'quote_index': 0}]})
        mocked.assert_not_called()


if __name__ == '__main__':
    unittest.main()
