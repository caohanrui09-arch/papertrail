"""Stage92 (restored): two-step follow-up picks read quotes, then answers from them."""
import unittest

from research90.followup import (answer_messages, quote_catalog, resolve, select_messages,
                                  select_schema, validate_answer, validate_picks)

PAPERS = [
    {'doc_id': 'a', 'title': 'A', 'abstract': 'abstract a', 'version_key': 'arxiv:av1',
     'source_url': 'https://arxiv.org/abs/av1',
     'quotes': [{'text': 'qa0'}, {'text': 'qa1'}]},
    {'doc_id': 'b', 'title': 'B', 'abstract': 'abstract b', 'version_key': 'arxiv:bv1',
     'source_url': 'https://arxiv.org/abs/bv1', 'quotes': [{'text': 'qb0'}]},
]


class CatalogTests(unittest.TestCase):
    def test_catalog_lists_every_read_quote(self):
        items = quote_catalog(PAPERS)
        self.assertEqual([(i['doc_id'], i['quote_index']) for i in items], [('a', 0), ('a', 1), ('b', 0)])

    def test_select_schema_enumerates_read_ids_only(self):
        schema = select_schema(PAPERS)
        self.assertEqual(schema['properties']['picks']['items']['properties']['doc_id']['enum'], ['a', 'b'])
        self.assertEqual(schema['properties']['picks']['items']['properties']['doc_id']['enum'], ['a', 'b'])
        self.assertEqual(schema['properties']['picks']['items']['properties']['quote_index']['maximum'], 1)


class ResolveTests(unittest.TestCase):
    def test_valid_pick_keeps_the_quote(self):
        resolved, error = resolve(PAPERS, [{'doc_id': 'a', 'quote_index': 1}])
        self.assertIsNone(error)
        self.assertEqual(resolved[0]['quote'], 'qa1')
        self.assertEqual(resolved[0]['quote_index'], 1)
        self.assertTrue(resolved[0]['source_verified'])

    def test_unread_id_is_rejected(self):
        resolved, error = resolve(PAPERS, [{'doc_id': 'zzz', 'quote_index': 0}])
        self.assertEqual(resolved, [])
        self.assertIn('was not read', error)

    def test_out_of_range_is_rejected(self):
        resolved, error = resolve(PAPERS, [{'doc_id': 'b', 'quote_index': 5}])
        self.assertEqual(resolved, [])
        self.assertIn('out of range', error)

    def test_duplicate_picks_collapse(self):
        resolved, error = resolve(PAPERS, [{'doc_id': 'a', 'quote_index': 0}, {'doc_id': 'a', 'quote_index': 0}])
        self.assertIsNone(error)
        self.assertEqual(len(resolved), 1)


class PickTests(unittest.TestCase):
    def test_user_picks_must_be_read(self):
        self.assertTrue(validate_picks(PAPERS, [{'doc_id': 'a', 'quote_index': 0}]))
        self.assertFalse(validate_picks(PAPERS, [{'doc_id': 'zzz', 'quote_index': 0}]))
        self.assertFalse(validate_picks(PAPERS, [{'doc_id': 'b', 'quote_index': 9}]))
        self.assertFalse(validate_picks(PAPERS, []))


class PromptTests(unittest.TestCase):
    def test_selector_lists_the_candidates(self):
        messages = select_messages('为什么？', PAPERS)
        self.assertIn('为什么？', messages[1]['content'])
        self.assertIn('[a] (0) qa0', messages[1]['content'])

    def test_answer_prompt_carries_the_evidence(self):
        messages = answer_messages('为什么？', [{'doc_id': 'a', 'text': 'qa1'}])
        self.assertIn('qa1', messages[1]['content'])

    def test_answer_validation(self):
        self.assertEqual(validate_answer({'answer': '  '})[0], None)
        self.assertEqual(validate_answer({'answer': '结论。'})[0], '结论。')
        self.assertIn('exactly answer', validate_answer({'answer': 'x', 'citations': []})[1])


if __name__ == '__main__':
    unittest.main()
