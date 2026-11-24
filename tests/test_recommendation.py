"""Real upstream recommendation, personalized search, and source boundaries."""
import importlib.util
import json
import tempfile
from pathlib import Path
import unittest

if importlib.util.find_spec("pandas") is None or importlib.util.find_spec("scipy") is None:
    raise unittest.SkipTest("Use original isolated stage6 runtime for recommendation tests")

import pandas as pd

from gsearch.data import write_json
from gsearch.discovery import DiscoverySession, make_tools
from gsearch.paper_recommendation import PaperRecommender, upstream_sar
from gsearch.retrieval import Corpus


def fixture() -> PaperRecommender:
    pairs = [("a", "1", 1), ("a", "4", -1), ("b", "1", 1), ("b", "2", 1),
             ("c", "1", 1), ("c", "2", 1), ("d", "3", 1), ("d", "4", 1),
             ("e", "3", 1), ("e", "4", 1), ("f", "3", 1), ("g", "4", 1)]
    return PaperRecommender(pd.DataFrame(pairs, columns=["user_id", "arxiv_id", "rating"]), ["1", "2", "3", "4"])


class RecommendationTests(unittest.TestCase):
    def test_original_sar_personalizes_and_filters_dislikes(self) -> None:
        engine = fixture()
        self.assertTrue(upstream_sar().__module__.startswith("recommenders."))
        hits = engine.recommend("a", 3)
        self.assertEqual(hits[0]["doc_id"], "2")
        self.assertFalse({"1", "4"} & {r["doc_id"] for r in hits})
        self.assertNotEqual([r["doc_id"] for r in engine.recommend("a", 3)],
                            [r["doc_id"] for r in engine.recommend("f", 3)])
        self.assertEqual(engine.explanation("a", "2")["history_contributions"][0]["arxiv_id"], "1")

    def test_cold_user_fallback_is_explicit(self) -> None:
        engine = fixture()
        self.assertTrue(all(r["cold_user_fallback"] for r in engine.recommend("new", 3)))
        self.assertEqual([r["doc_id"] for r in engine.recommend("new", 3)],
                         [r["doc_id"] for r in engine.recommend("new", 3, "popular")])

    def test_real_tools_search_recommend_read_and_budget(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"documents.json"
            write_json(path, [{"doc_id": x, "code": x, "title": "paper", "sentences": ["shared research abstract "+x]}
                              for x in ("1", "2", "3", "4")])
            session = DiscoverySession(fixture(), Corpus(path), "a", max_calls=4)
            tools = {t.name: t for t in make_tools(session)}
            self.assertIn("error", tools["read_paper"](doc_id="2"))
            rec = tools["recommend_papers"](k=2)
            self.assertEqual(rec["papers"][0]["doc_id"], "2")
            found = tools["search_papers"](query="research", k=2)
            self.assertIn("SAR", found["ranking"])
            original = tools["read_paper"](doc_id="2")
            self.assertEqual(original["abstract"], "shared research abstract 2")
            self.assertFalse(original["semantic_stance_verified"])
            with self.assertRaises(ValueError):
                session.recommend()
            session.lexical.db.close()

    def test_corpus_mismatch_cannot_mix_scifact_ids(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"documents.json"
            write_json(path, [{"doc_id": "scifact:1", "code": "1", "title": "x", "sentences": ["x"]}])
            with self.assertRaises(ValueError):
                DiscoverySession(fixture(), Corpus(path), "a")

    def test_real_agent_framework_rejects_unread_final_paper(self) -> None:
        from smolagents import Model
        from smolagents.models import ChatMessage, MessageRole
        from gsearch.recommendation_agent import run

        class ScriptedModel(Model):
            def __init__(inner) -> None:
                super().__init__(model_id="discovery_contract_only")
                inner.calls = iter([
                    {"name": "recommend_papers", "arguments": {"k": 2}},
                    {"name": "final_answer", "arguments": {"answer": {"paper_ids": ["2"]}}},
                    {"name": "read_paper", "arguments": {"doc_id": "2"}},
                    {"name": "final_answer", "arguments": {"answer": {"paper_ids": ["2"]}}}])

            def generate(inner, messages: list, **kwargs: object) -> ChatMessage:
                return ChatMessage(role=MessageRole.ASSISTANT, content=json.dumps(next(inner.calls)))

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"documents.json"
            write_json(path, [{"doc_id": x, "code": x, "title": "paper", "sentences": ["original abstract "+x]}
                              for x in ("1", "2", "3", "4")])
            session = DiscoverySession(fixture(), Corpus(path), "a")
            result = run(session, "Select a recommended original paper", ScriptedModel())
            self.assertTrue(result["source_checked_selection"])
            self.assertEqual(result["answer"], {"paper_ids": ["2"]})
            self.assertTrue(any(s.get("error") for s in result["steps"]))
            session.lexical.db.close()


if __name__ == "__main__":
    unittest.main()
