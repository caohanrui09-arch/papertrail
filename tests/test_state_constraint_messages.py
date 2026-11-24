"""Stage81-A regression: wording may change, decisions and accounting may not.

The frozen pre-change module is the oracle. Every scripted and randomised
proposal is replayed against both implementations; accept/reject and counters
must match exactly. Message content is then checked separately on the new one.
"""
import json
import random
from types import SimpleNamespace
import unittest

from research81.frozen_state_constraints_v79 import ActionState as FrozenState
from gsearch.state_constraints import ActionState as CurrentState


def paper(doc, quotes=1):
    return {'doc_id': doc, 'quotes': [{'quote_index': i, 'text': 'original fixture'} for i in range(quotes)]}


def attempt(state, name, arguments):
    try:
        state.validate(name, arguments)
        return ('ok', '')
    except ValueError as error:
        return ('reject', str(error))


class FakeTool:
    def __init__(self):
        self.inputs = {'k': {}, 'doc_id': {}, 'answer': {}}


class FakeAgent:
    def __init__(self):
        self.tools = {}
        self.instructions = ''
        self.system_prompt = 'system'
        self.memory = SimpleNamespace(system_prompt=SimpleNamespace(system_prompt=''))


def tool_table():
    return {name: FakeTool() for name in ('search_papers', 'recommend_papers', 'read_paper', 'final_answer')}


# Each operation is replayed on both states in the same order.
SCENARIOS = {
    'search_happy_and_rejections': [
        ('validate', 'search_papers', {'query': 'x', 'k': 3}),
        ('validate', 'read_paper', {'doc_id': 'a'}),
        ('observe', 'search_papers', {'papers': [{'doc_id': 'a'}, {'doc_id': 'b'}]}),
        ('validate', 'search_papers', {'query': 'x', 'k': 3}),
        ('validate', 'finalize', {'citations': [{'doc_id': 'a', 'quote_index': 0}]}),
        ('observe', 'read_paper', paper('a')),
        ('validate', 'read_paper', {'doc_id': 'a'}),
        ('validate', 'read_paper', {'doc_id': 'zzz'}),
        ('validate', 'finalize', {'citations': [{'doc_id': 'a', 'quote_index': 0}]}),
        ('observe', 'finalize', {'citations': [{'doc_id': 'a', 'quote_index': 0}]}),
        ('validate', 'read_paper', {'doc_id': 'b'}),
    ],
    'mixed_opposite_order': [
        ('observe', 'recommend_papers', {'papers': [{'doc_id': 'r1'}, {'doc_id': 'r2'}]}),
        ('observe', 'read_paper', paper('r1')),
        ('observe', 'search_papers', {'papers': [{'doc_id': 's1'}]}),
        ('validate', 'read_paper', {'doc_id': 's1'}),
        ('observe', 'read_paper', paper('s1')),
        ('validate', 'finalize', {'citations': [{'doc_id': 's1', 'quote_index': 0}, {'doc_id': 'r1', 'quote_index': 0}]}),
    ],
    'mixed_wrong_branch_then_retrieval': [
        ('observe', 'search_papers', {'papers': [{'doc_id': 's1'}, {'doc_id': 's2'}]}),
        ('observe', 'recommend_papers', {'papers': [{'doc_id': 'r1'}]}),
        ('observe', 'read_paper', paper('s1')),
        ('validate', 'read_paper', {'doc_id': 's2'}),
        ('validate', 'search_papers', {'query': 'x', 'k': 3}),
    ],
    'zero_result_finalize': [
        ('observe', 'search_papers', {'papers': []}),
        ('validate', 'finalize', {'citations': [{'doc_id': 'fake', 'quote_index': 0}]}),
        ('validate', 'finalize', {'citations': []}),
    ],
    'schema_shapes': [
        ('validate', 'search_papers', {'query': 'x', 'k': None}),
        ('validate', 'search_papers', {'query': 'x', 'k': 0}),
        ('validate', 'search_papers', {'query': 'x', 'k': 4}),
        ('validate', 'search_papers', {'query': 'x', 'k': True}),
        ('validate', 'search_papers', {'query': '', 'k': 3}),
        ('validate', 'search_papers', {'query': 'x' * 2001, 'k': 3}),
        ('validate', 'search_papers', {'query': 'x', 'k': 3}),
    ],
    'citation_shapes': [
        ('observe', 'recommend_papers', {'papers': [{'doc_id': 'a'}, {'doc_id': 'b'}]}),
        ('observe', 'read_paper', paper('a')),
        ('observe', 'read_paper', paper('b')),
        ('validate', 'finalize', {'citations': {}}),
        ('validate', 'finalize', {'citations': [{'doc_id': 'a', 'quote_index': 0}]}),
        ('validate', 'finalize', {'citations': [{'doc_id': 'a', 'extra': 1, 'quote_index': 0}]}),
        ('validate', 'finalize', {'citations': [{'doc_id': 'a', 'quote_index': 0}, {'doc_id': 'a', 'quote_index': 0}]}),
        ('validate', 'finalize', {'citations': [{'doc_id': 'nope', 'quote_index': 0}]}),
        ('validate', 'finalize', {'citations': [{'doc_id': 'a', 'quote_index': 9}]}),
        ('validate', 'finalize', {'citations': [{'doc_id': 'a', 'quote_index': 0}]}),
    ],
}


class DifferentialDecisionTests(unittest.TestCase):
    def replay(self, scenario, intent):
        frozen, current = FrozenState({'intent': intent}), CurrentState({'intent': intent})
        for op in scenario:
            if op[0] == 'validate':
                left, right = attempt(frozen, op[1], op[2]), attempt(current, op[1], op[2])
                self.assertEqual(left[0], right[0], f'decision drifted on {op[1]}: {left} vs {right}')
                self.assertEqual(frozen.charged, current.charged)
                self.assertEqual(frozen.retrieval_charges, current.retrieval_charges)
                self.assertEqual(frozen.read_charges, current.read_charges)
                self.assertEqual(frozen.readable(), current.readable())
                self.assertEqual(frozen.legal(), current.legal())
            elif op[0] == 'observe':
                frozen.observe(op[1], op[2]); current.observe(op[1], op[2])
            elif op[0] == 'charge':
                frozen.charge(op[1], op[2]); current.charge(op[1], op[2])
        self.assertEqual(frozen.charged, current.charged)
        self.assertEqual(frozen.readable(), current.readable())
        self.assertEqual(frozen.legal(), current.legal())
        self.assertEqual(frozen.can_finish(), current.can_finish())
        self.assertEqual(frozen.final_count(), current.final_count())

    def test_scripted_scenarios_decide_identically(self):
        for name, scenario in SCENARIOS.items():
            intent = 'mixed' if name.startswith('mixed') else 'search'
            with self.subTest(scenario=name):
                self.replay(scenario, intent)

    def test_accounting_change_is_deliberate(self):
        # Stage82-B changes accounting on purpose; the v79 oracle still charges the
        # rejected proposal while the live state counts it as a separate rejection.
        frozen, current = FrozenState({'intent': 'search'}), CurrentState({'intent': 'search'})
        calls = [{'name': 'search_papers', 'arguments': {'query': 'x', 'k': None}}]
        frozen.charge(calls, 'invalid')
        current.charge(calls, 'invalid')
        self.assertEqual(frozen.charged, 1)
        self.assertEqual(current.charged, 0)
        self.assertEqual(current.rejected, 1)
        self.assertEqual(frozen.legal(), current.legal())

    def test_randomised_proposals_decide_identically(self):
        random.seed(20261122)
        actions = [
            ('search_papers', {'query': 'x', 'k': 3}), ('search_papers', {'query': 'x', 'k': None}),
            ('recommend_papers', {'k': 2}), ('read_paper', {'doc_id': 'a'}),
            ('read_paper', {'doc_id': 'b'}), ('read_paper', {'doc_id': 'q'}),
            ('finalize', {'citations': []}), ('finalize', {'citations': [{'doc_id': 'a', 'quote_index': 0}]}),
            ('finalize', {'citations': [{'doc_id': 'b', 'quote_index': 0}]}),
        ]
        for _ in range(300):
            intent = random.choice(['search', 'recommend', 'mixed', 'empty'])
            frozen, current = FrozenState({'intent': intent}), CurrentState({'intent': intent})
            for _ in range(random.randint(1, 5)):
                action = random.choice(actions)
                self.assertEqual(attempt(frozen, *action)[0], attempt(current, *action)[0])
        self.assertTrue(True)


class MessageTests(unittest.TestCase):
    def reason(self, state, name, arguments):
        with self.assertRaises(ValueError) as caught:
            state.validate(name, arguments)
        text = str(caught.exception)
        self.assertTrue(text.startswith('reason='), text)
        return text.split()[0].split('=', 1)[1], text

    def test_never_read_id_is_not_called_already_read(self):
        state = CurrentState({'intent': 'search'})
        state.observe('search_papers', {'papers': [{'doc_id': 'a'}]})
        code, text = self.reason(state, 'read_paper', {'doc_id': 'nope'})
        self.assertEqual(code, 'read_never_returned')
        self.assertNotIn('already read', text)
        self.assertIn('never returned', text)

    def test_already_read_is_named(self):
        state = CurrentState({'intent': 'search'})
        state.observe('search_papers', {'papers': [{'doc_id': 'a'}]})
        state.observe('read_paper', paper('a'))
        code, text = self.reason(state, 'read_paper', {'doc_id': 'a'})
        self.assertEqual(code, 'read_already_read')
        self.assertIn('already read', text)

    def test_mixed_wrong_branch_names_required_branch(self):
        state = CurrentState({'intent': 'mixed'})
        state.observe('search_papers', {'papers': [{'doc_id': 's1'}, {'doc_id': 's2'}]})
        state.observe('recommend_papers', {'papers': [{'doc_id': 'r1'}]})
        state.observe('read_paper', paper('s1'))
        code, text = self.reason(state, 'read_paper', {'doc_id': 's2'})
        self.assertEqual(code, 'read_wrong_branch')
        self.assertIn('recommend_papers', text)
        self.assertIn('s2', text)

    def test_zero_result_citation_count_explains_zero(self):
        state = CurrentState({'intent': 'search'})
        state.observe('search_papers', {'papers': []})
        code, text = self.reason(state, 'finalize', {'citations': [{'doc_id': 'fake', 'quote_index': 0}]})
        self.assertEqual(code, 'final_citation_count')
        self.assertIn('expected exactly 0', text)
        self.assertIn('returned=0', text)

    def test_invalid_k_reports_actual_value(self):
        state = CurrentState({'intent': 'search'})
        code, text = self.reason(state, 'search_papers', {'query': 'x', 'k': None})
        self.assertEqual(code, 'invalid_k')
        self.assertIn('got None', text)

    def test_budget_exhaustion_is_explicit(self):
        # Six actions that reached the server are what exhausts the budget.
        state = CurrentState({'intent': 'search'})
        for _ in range(6):
            state.wire.append({'name': 'search_papers', 'arguments': {}, 'sent_to_server': True})
            state.charge([{'name': 'search_papers', 'arguments': {'query': 'x', 'k': 3}}], None)
        code, text = self.reason(state, 'search_papers', {'query': 'x', 'k': 3})
        self.assertEqual(code, 'budget_exhausted')
        self.assertIn('attempts=6/6', text)

    def test_terminal_instruction_replaces_call_request(self):
        state = CurrentState({'intent': 'search'})
        tools = tool_table()
        for _ in range(6):
            state.wire.append({'name': 'search_papers', 'arguments': {}, 'sent_to_server': True})
            state.charge([{'name': 'search_papers', 'arguments': {'query': 'x', 'k': 3}}], None)
        agent = FakeAgent()
        state.refresh(agent, tools)
        self.assertIn('TERMINAL', agent.instructions)
        self.assertNotIn('Generate a legal call', agent.instructions)
        self.assertEqual(agent.tools, {})

    def test_live_instruction_still_asks_for_a_call(self):
        state = CurrentState({'intent': 'search'})
        tools = tool_table()
        agent = FakeAgent()
        state.refresh(agent, tools)
        self.assertIn('Generate a legal call', agent.instructions)
        self.assertEqual(set(agent.tools), {'search_papers'})


if __name__ == '__main__':
    unittest.main()
