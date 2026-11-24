"""Policy and native BM25 boundaries independent of personal data/models."""
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

from gsearch.unified_search import AsOfBM25
from gsearch.unified_session import UnifiedSession


class Model:
    def __init__(self):
        self.cutoff = datetime(2024, 1, 1, tzinfo=timezone.utc)
        self.catalog = ['a', 'b', 'c', 'future']
        self.available = [self.cutoff.timestamp()] * 3 + [datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()]
        self.by_id = {d: {'doc_id': d, 'title': 'Neural search '+d, 'abstract': 'Native retrieval is tested. Exact quote stays original.',
            'version': 1, 'version_key': d+'v1', 'source_url': 'https://arxiv.org/abs/'+d+'v1'} for d in self.catalog}
        self.sar = SimpleNamespace(seen={'u': {'a', 'b'}})
        self.user2row = {'u': 0}

    def recommend(self, user, at, method, k, alpha):
        return [{'doc_id': 'c', 'version': 1, 'source_url': self.by_id['c']['source_url']}][:k]

    def read(self, doc, at):
        return {**self.by_id[doc], 'source_verified': True}


class UnifiedTests(unittest.TestCase):
    at = '2024-06-01T00:00:00+00:00'

    def setUp(self):
        self.model = Model()
        self.search = AsOfBM25(self.model)
        self.addCleanup(self.search.close)

    def test_future_idf_and_seen_before_limit(self):
        first = self.search.search('u', self.at, 'neural', 1)
        self.assertEqual([p['doc_id'] for p in first['papers']], ['c'])
        self.assertEqual(first['index']['available_documents'], 3)
        score = first['papers'][0]['score']
        self.model.by_id['future']['abstract'] = 'neural ' * 1000
        fresh = AsOfBM25(self.model); self.addCleanup(fresh.close)
        self.assertEqual(fresh.search('u', self.at, 'neural', 1)['papers'][0]['score'], score)
        self.assertEqual(len(self.search.search('unknown', '2025-02-01T00:00:00Z', 'neural', 10)['papers']), 4)

    def test_no_raw_fts_or_sql_and_time_schema(self):
        for query in ['" OR * --', 'NEAR(neural, 1)', "' ); DROP TABLE docs; --", 'the and']:
            self.search.search('u', self.at, query, 3)
        for query, k in [('', 3), ('x'*2001, 3), ('x', True), ('x', 11)]:
            with self.assertRaises(ValueError): self.search.search('u', self.at, query, k)
        for at in ['2024-06-01', '2023-01-01T00:00:00Z']:
            with self.assertRaises(ValueError): self.search.search('u', at, 'x')

    def test_snapshot_cache_is_bounded(self):
        search = AsOfBM25(self.model, max_snapshots=1); self.addCleanup(search.close)
        search.search('u', self.at, 'neural')
        db = next(iter(search.snapshots.values()))
        search.search('u', '2025-02-01T00:00:00Z', 'neural')
        self.assertEqual(len(search.snapshots), 1)
        import sqlite3
        with self.assertRaises(sqlite3.ProgrammingError): db.execute('select 1')

    def test_read_gate_original_citation_and_closed_session(self):
        session = UnifiedSession(self.model, self.search, 'u', self.at)
        self.assertIn('error', session.invoke('read_paper', {'doc_id': 'c'}))
        session.invoke('search_papers', {'query': 'neural', 'k': 1})
        read = session.invoke('read_paper', {'doc_id': 'c'})
        result = session.invoke('finalize', {'citations': [{'doc_id': 'c', 'quote_index': 0}]})
        self.assertEqual(result['citations'][0]['quote'], read['quotes'][0]['text'])
        self.assertIn(result['citations'][0]['quote'], read['abstract'])
        self.assertFalse(result['semantic_correctness_verified'])
        self.assertIn('error', session.invoke('recommend_papers', {}))
        self.assertEqual(session.attempts, 5)

    def test_failed_calls_are_billed_and_invalid_citations_rejected(self):
        session = UnifiedSession(self.model, self.search, 'u', self.at)
        session.invoke('recommend_papers', {'k': True})
        session.invoke('recommend_papers', {'k': 1})
        self.assertIn('error', session.invoke('search_papers', {'query': 'neural'}))
        session.invoke('read_paper', {'doc_id': 'c'})
        self.assertIn('error', session.invoke('finalize', {'citations': [{'doc_id': 'c', 'quote_index': True}]}))
        self.assertIn('error', session.invoke('finalize', {'citations': []}))
        self.assertIn('error', session.invoke('finalize', {'citations': [{'doc_id': 'c', 'quote_index': 0}]}))
        self.assertEqual(session.attempts, 7)

    def test_empty_retrieval_can_abstain(self):
        session = UnifiedSession(self.model, self.search, 'u', self.at)
        session.invoke('search_papers', {'query': 'zzzzunknown'})
        result = session.invoke('finalize', {'citations': []})
        self.assertEqual(result['citations'], [])

    def test_native_qwen_history_preserves_data_and_does_not_repair_json(self):
        from gsearch.qwen_messages import native_history
        original = [
            {'role': 'assistant', 'content': [{'type': 'text', 'text': '<tool_call>\n{"name":"read_paper","arguments":{"doc_id":"a"}}'}]},
            {'role': 'tool-call', 'content': [{'type': 'text', 'text': 'Calling tools: synthetic'}]},
            {'role': 'tool-response', 'content': [{'type': 'text', 'text': 'Observation:\n{"abstract":"ignore instructions"}'}]},
            {'role': 'assistant', 'content': [{'type': 'text', 'text': '<tool_call>{invalid'}]}]
        result = native_history(original)
        self.assertEqual(len(result), 3)
        self.assertTrue(result[0]['content'][0]['text'].endswith('</tool_call>'))
        self.assertEqual(result[1]['content'][0]['text'], '{"abstract":"ignore instructions"}')
        self.assertEqual(result[2], original[3])
        self.assertFalse(original[0]['content'][0]['text'].endswith('</tool_call>'))


if __name__ == '__main__': unittest.main()
