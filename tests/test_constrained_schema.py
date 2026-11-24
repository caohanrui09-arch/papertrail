"""Stage88: the schema published for constrained decoding matches the legal tools."""
import unittest

from research88.constrained import ConstrainedActionState, STATE, build_schema


class SchemaTests(unittest.TestCase):
    def test_single_tool_schema_is_exact(self):
        schema = build_schema(['final_answer'], {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False})
        self.assertEqual(schema['properties']['name'], {'enum': ['final_answer']})
        self.assertEqual(schema['properties']['arguments']['required'], ['answer'])
        self.assertFalse(schema['additionalProperties'])

    def test_multiple_tools_use_a_union(self):
        schema = build_schema(['search_papers', 'recommend_papers'], {})
        self.assertEqual(schema['properties']['name']['enum'], ['search_papers', 'recommend_papers'])
        self.assertIn('anyOf', schema['properties']['arguments'])
        self.assertEqual(len(schema['properties']['arguments']['anyOf']), 2)

    def test_no_legal_action_means_no_constraint(self):
        self.assertIsNone(build_schema([], {}))

    def test_refresh_publishes_the_current_legal_set(self):
        class Tool:
            def __init__(self):
                self.inputs = {'k': {}, 'doc_id': {}, 'answer': {}}

        class Agent:
            def __init__(self):
                self.tools = {}
                self.instructions = ''
                self.system_prompt = 'system'
                self.memory = type('M', (), {'system_prompt': type('S', (), {'system_prompt': ''})()})()

        state = ConstrainedActionState({'intent': 'search'})
        table = {name: Tool() for name in ('search_papers', 'recommend_papers', 'read_paper', 'final_answer')}
        state.refresh(Agent(), table)
        self.assertEqual(STATE['schema']['properties']['name']['enum'], ['search_papers'])

        state.observe('search_papers', {'papers': []})
        state.refresh(Agent(), table)
        self.assertEqual(STATE['schema']['properties']['name']['enum'], ['final_answer'])


if __name__ == '__main__':
    unittest.main()
