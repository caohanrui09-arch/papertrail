import json
from pathlib import Path
import tempfile
import unittest

from gsearch.agent import EvidenceSession, build_tools, run_agent
from gsearch.evaluate import metrics
from gsearch.retrieval import BM25, Corpus, DocumentTrie


class CorrectnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        path = Path(self.directory.name) / "documents.json"
        path.write_text(json.dumps([
            {"doc_id": "101", "code": "00000", "title": "Cells and oxygen",
             "sentences": ["Oxygen increases cell growth.", "No effect was seen at low concentrations."]},
            {"doc_id": "202", "code": "00001", "title": "Water samples",
             "sentences": ["Water samples were collected."]}]), encoding="utf-8")
        self.corpus = Corpus(path)
        self.session = EvidenceSession(self.corpus, {"bm25": BM25(self.corpus)}, max_searches=2, max_reads=2)

    def tearDown(self) -> None:
        self.session.retrievers["bm25"].db.close()
        self.directory.cleanup()

    def test_duplicate_and_invalid_predictions_consume_ranking_slots(self) -> None:
        actual = metrics([None, "101", "101", "202"], {"101", "202"}, 3)
        self.assertEqual(actual["recall"], 0.5)
        self.assertEqual(actual["mrr"], 0.5)
        self.assertLess(actual["ndcg"], 1)
        with self.assertRaises(ValueError):
            metrics([], set(), 10)

    def test_fts_query_cannot_inject_query_operators(self) -> None:
        hits = self.session.search('oxygen " OR title:water --', "bm25", 2)
        self.assertNotIn("error", hits)
        self.assertTrue(all(h["doc_id"] in self.corpus.by_id for h in hits["hits"]))
        self.assertEqual(self.session.search("!!!", "bm25", 2)["hits"], [])
        self.assertIn("error", self.session.search("oxygen", "bm25", 2))

    def test_must_search_then_read_before_citing(self) -> None:
        self.assertIn("error", self.session.record("101", [0], "SUPPORT"))
        self.session.search("oxygen", "bm25", 2)
        self.assertIn("error", self.session.record("101", [0], "SUPPORT"))
        read = self.session.read_document("101")
        self.assertNotIn("evidence", read)
        self.assertNotIn("label", read)
        cited = self.session.record("101", [0], "SUPPORT")
        self.assertEqual(cited["quotes"], ["Oxygen increases cell growth."])
        self.assertFalse(cited["semantic_stance_verified"])
        self.assertIn("error", self.session.record("101", [-1], "SUPPORT"))
        self.assertIn("error", self.session.record("101", [True], "SUPPORT"))

    def test_unknown_ids_and_read_budget_are_enforced(self) -> None:
        self.assertIn("error", self.session.read_document("999"))
        self.session.search("oxygen", "bm25", 2)
        self.assertNotIn("error", self.session.read_document("101"))
        self.assertIn("error", self.session.read_document("101"))

    def test_framework_loop_with_scripted_model_is_only_a_contract_test(self) -> None:
        from smolagents import Model
        from smolagents.models import ChatMessage, MessageRole

        class ScriptedModel(Model):
            def __init__(self):
                super().__init__(model_id="scripted_contract_test")
                self.calls = iter([
                    {"name": "search_documents", "arguments": {"query": "oxygen", "method": "bm25", "k": 2}},
                    {"name": "read_document", "arguments": {"doc_id": "101"}},
                    {"name": "record_evidence", "arguments": {"doc_id": "101", "sentence_ids": [0], "stance": "SUPPORT"}},
                    {"name": "final_answer", "arguments": {"answer": "SUPPORT [101:0]"}}])

            def generate(self, messages: list, **kwargs: object) -> ChatMessage:
                return ChatMessage(role=MessageRole.ASSISTANT, content=json.dumps(next(self.calls)))

        result = run_agent(self.session, "Oxygen increases cell growth.", ScriptedModel())
        self.assertIsNone(result["error"])
        self.assertEqual([r["tool"] for r in result["tool_trace"]],
                         ["search_documents", "read_document", "record_evidence"])
        self.assertEqual(result["evidence"][0]["quotes"], ["Oxygen increases cell growth."])
        self.assertTrue(result["completed_protocol"])

    def test_source_existence_does_not_imply_correct_scientific_stance(self) -> None:
        from gsearch.benchmark_agent import score_report
        report = {"answer": "SUPPORT", "evidence": [{"doc_id": "101", "sentence_ids": [0], "model_stance": "SUPPORT"}],
                  "tool_trace": [], "agent_steps": [], "seconds": 0, "budget_exhausted": False}
        gold = {"id": 1, "evidence": {"101": [{"sentences": [0], "label": "CONTRADICT"}]}}
        scored = score_report(report, gold)
        self.assertEqual(scored["recorded_document_recall"], 1.0)
        self.assertFalse(scored["complete_rationale_and_stance"])

    def test_trie_consumes_decoder_start_and_requires_full_id(self) -> None:
        class Tokenizer:
            eos_token_id = 1

            def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
                return [int(c) + 2 for c in text]

        class Output(list):
            def tolist(self) -> list[int]:
                return list(self)

        trie = DocumentTrie(Tokenizer(), ["00", "01"])
        self.assertEqual(trie.allowed(0, Output([0])), [2])
        self.assertEqual(trie.allowed(0, Output([0, 2])), [2, 3])
        self.assertEqual(trie.allowed(0, Output([0, 2, 3])), [1])
        with self.assertRaises(ValueError):
            trie.allowed(0, Output([0, 7]))

    def test_native_tool_stop_handles_marker_inside_a_newline_token(self) -> None:
        import torch
        from gsearch.local_model import LocalToolModel
        from smolagents.models import ChatMessage, MessageRole

        class Tokenizer:
            def decode(self, tokens: object, **kwargs: object) -> str:
                return "</tool_call>\n"

        model = object.__new__(LocalToolModel)
        stopping = model.make_stopping_criteria(["</tool_call>"], Tokenizer())
        self.assertTrue(stopping[0](torch.tensor([[2]]), None))
        message = ChatMessage(role=MessageRole.ASSISTANT,
                              content='<tool_call>{"name":"read_document","arguments":{"doc_id":"101"}}</tool_call>\n')
        self.assertEqual(model.parse_tool_calls(message).tool_calls[0].function.name, "read_document")


if __name__ == "__main__":
    unittest.main()
