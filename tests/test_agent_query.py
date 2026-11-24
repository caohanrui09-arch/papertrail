"""Stage95: a custom plan may hand the search-query choice to the agent."""
import unittest

from research71.clients import enforces_query


class QueryModeTests(unittest.TestCase):
    def test_confirmed_custom_task_still_binds_the_query(self):
        self.assertTrue(enforces_query({'task_kind': 'custom', 'query': 'x'}))

    def test_model_mode_releases_the_query(self):
        self.assertFalse(enforces_query({'task_kind': 'custom', 'query_mode': 'model'}))

    def test_preset_task_is_unaffected(self):
        self.assertFalse(enforces_query({'task_kind': 'preset'}))


if __name__ == '__main__':
    unittest.main()
