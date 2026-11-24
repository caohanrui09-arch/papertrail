"""Stage97: an agent that owns its query may refine the search once."""
import unittest

from gsearch.state_constraints import ActionState


def searched(query_mode: str, charges: int = 1) -> ActionState:
    task = {'intent': 'search', 'query': 'x'}
    if query_mode:
        task['query_mode'] = query_mode
    state = ActionState(task)
    state.retrieved = {'search_papers'}
    state.returned = {'2401.00001': {'search_papers'}}
    state.retrieval_charges = charges
    return state


class RefinementTests(unittest.TestCase):
    def test_model_mode_offers_a_second_search(self):
        self.assertIn('search_papers', searched('model').legal())

    def test_confirmed_mode_does_not(self):
        self.assertNotIn('search_papers', searched(None).legal())

    def test_second_search_closes_after_two_charges(self):
        self.assertNotIn('search_papers', searched('model', charges=2).legal())

    def test_rejection_reason_names_the_budget_when_exhausted(self):
        state = searched('model', charges=2)
        with self.assertRaises(ValueError) as caught:
            state.validate('search_papers', {'query': '另一种说法', 'k': 2})
        self.assertIn('reason=retrieval_budget_exhausted', str(caught.exception))

    def test_rejection_reason_in_confirmed_mode_is_already_used(self):
        state = searched(None)
        with self.assertRaises(ValueError) as caught:
            state.validate('search_papers', {'query': '另一种说法', 'k': 2})
        self.assertIn('reason=search_papers_already_used', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
