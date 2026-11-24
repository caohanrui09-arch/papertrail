"""Stage82-B regression: rejected proposals are free, six served actions still cap.

The frozen v81 module is kept as the pre-change oracle so the accounting change
is demonstrated rather than asserted by deletion.
"""
import json
from unittest.mock import patch
import unittest

from gsearch.state_constraints import ActionState
from research82.frozen_state_constraints_v81 import ActionState as FrozenV81


def sent(name, arguments=None):
    return {'name': name, 'arguments': arguments or {'k': 3}, 'sent_to_server': True}


def rejected(name, error='State action unavailable', arguments=None):
    return {'name': name, 'arguments': arguments or {'k': 3}, 'sent_to_server': False, 'error': error}


class AccountingTests(unittest.TestCase):
    def test_rejected_proposal_does_not_consume_the_six(self):
        state = ActionState({'intent': 'search'})
        state.wire.append(rejected('search_papers', 'reason=invalid_k'))
        state.charge([{'name': 'search_papers', 'arguments': {'query': 'x', 'k': None}}], 'invalid_k')
        self.assertEqual(state.rejected, 1)
        self.assertEqual(state.charged, 0)
        self.assertIn('search_papers', state.legal())

    def test_sent_proposal_consumes_the_six(self):
        state = ActionState({'intent': 'search'})
        state.wire.append(sent('search_papers'))
        state.charge([{'name': 'search_papers', 'arguments': {'query': 'x', 'k': 3}}], None)
        self.assertEqual(state.charged, 1)
        self.assertEqual(state.rejected, 0)

    def test_six_served_actions_still_cap_the_run(self):
        state = ActionState({'intent': 'search'})
        for _ in range(6):
            state.wire.append(sent('search_papers'))
            state.charge([{'name': 'search_papers', 'arguments': {'query': 'x', 'k': 3}}], None)
        self.assertEqual(state.charged, 6)
        self.assertEqual(state.legal(), [])
        state.wire.append(sent('search_papers'))
        state.charge([{'name': 'search_papers', 'arguments': {'query': 'x', 'k': 3}}], None)
        self.assertEqual(state.charged, 6)
        self.assertEqual(state.rejected, 1)

    def test_finalize_is_a_served_action(self):
        state = ActionState({'intent': 'search'})
        state.observe('search_papers', {'papers': [{'doc_id': 'a'}]})
        state.observe('read_paper', {'doc_id': 'a', 'quotes': [{'quote_index': 0}]})
        state.wire.append(sent('finalize', {'citations': [{'doc_id': 'a', 'quote_index': 0}]}))
        state.charge([{'name': 'final_answer', 'arguments': {'answer': {'citations': [{'doc_id': 'a', 'quote_index': 0}]}}}], None)
        self.assertEqual(state.charged, 1)
        self.assertEqual(state.rejected, 0)

    def test_frozen_v81_charged_the_same_proposal(self):
        old = FrozenV81({'intent': 'search'})
        old.charge([{'name': 'search_papers', 'arguments': {'query': 'x', 'k': None}}], 'invalid')
        self.assertEqual(old.charged, 1)
        self.assertFalse(hasattr(old, 'rejected'))

    def test_snapshot_does_not_add_new_text_fields(self):
        # Ablation (stage82): adding two informational JSON keys to the state string
        # deterministically derailed e73-recommend (2/2 -> 0/2), so the accounting lives
        # in the counters and the audit trail, not in extra model-visible fields.
        class Tool:
            def __init__(self):
                self.inputs = {'k': {}, 'doc_id': {}, 'answer': {}}

        class Agent:
            def __init__(self):
                self.tools = {}
                self.instructions = ''
                self.system_prompt = 'system'
                self.memory = type('M', (), {'system_prompt': type('S', (), {'system_prompt': ''})()})()

        state = ActionState({'intent': 'search'})
        state.wire.append(rejected('search_papers'))
        state.charge([{'name': 'search_papers', 'arguments': {'query': 'x', 'k': None}}], 'invalid')
        agent = Agent()
        state.refresh(agent, {name: Tool() for name in ('search_papers', 'recommend_papers', 'read_paper', 'final_answer')})
        snapshot = state.snapshots[-1]
        self.assertEqual(state.rejected, 1)
        self.assertEqual(snapshot['application_attempts_remaining'], 6)
        self.assertNotIn('rejected_proposals', snapshot)
        self.assertNotIn('rejected_proposals_are_free', snapshot)


class EndToEndTests(unittest.TestCase):
    def test_one_rejected_proposal_then_a_valid_run_completes(self):
        from smolagents.models import Model, ChatMessage
        from smolagents.monitoring import TokenUsage
        from gsearch.budget_model import GenerationMeter
        from gsearch.constrained_agent import run
        from gsearch.unified_session import UnifiedSession
        from gsearch.unified_search import AsOfBM25
        from tests.test_unified import Model as FixtureCorpus

        calls = [
            ('recommend_papers', {'k': None}),
            ('recommend_papers', {'k': 3}),
            ('read_paper', {'doc_id': 'c'}),
            ('final_answer', {'answer': {'citations': [{'doc_id': 'c', 'quote_index': 0}]}}),
        ]

        class Scripted(Model):
            def __init__(self):
                super().__init__(model_id='unit-script-not-a-real-LLM')
                self.index = 0

            def reset_budget(self, budget):
                self.meter = GenerationMeter(budget)

            def generate(self, messages, **kwargs):
                self.meter.reserve_input(1)
                self.meter.record_output(1)
                name, arguments = calls[self.index]
                self.index += 1
                return ChatMessage(role='assistant',
                                   content=json.dumps({'name': name, 'arguments': arguments}),
                                   token_usage=TokenUsage(input_tokens=1, output_tokens=1))

        corpus = FixtureCorpus()
        search = AsOfBM25(corpus)
        self.addCleanup(search.close)
        session = UnifiedSession(corpus, search, 'u', '2024-06-01T00:00:00Z')

        def transport(method, path, data=None, port=8766):
            if path == '/sessions':
                return 200, {'session_id': 'fixture'}
            if method == 'GET':
                return 200, session.snapshot()
            if method == 'DELETE':
                return 200, {'deleted': True}
            result = session.invoke(data['name'], data['arguments'])
            return (400, {'detail': result['error']}) if 'error' in result else (200, result)

        task = {'id': 'unit', 'intent': 'recommend', 'query': '', 'instruction': 'unit fixture only',
                'user_id': 'u', 'at': '2024-06-01T00:00:00Z'}
        with patch('gsearch.unified_agent.request', side_effect=transport):
            result = run(task, Scripted())

        self.assertTrue(result['completed_protocol'])
        self.assertEqual(result['metadata']['charged_application_attempts'], 3)
        events = result['metadata']['proposal_events']
        self.assertEqual(len(events), 4)
        self.assertFalse(events[0]['charged'])
        self.assertEqual(events[0]['rejected_total'], 1)
        self.assertTrue(all(event['charged'] for event in events[1:]))


if __name__ == '__main__':
    unittest.main()
