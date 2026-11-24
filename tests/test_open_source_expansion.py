import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

if importlib.util.find_spec("pyterrier") is None:
    raise unittest.SkipTest("Stage6 requires its isolated PyTerrier environment")

import numpy as np
import pyterrier as pt

from gsearch.agent import EvidenceSession
from gsearch.open_source_expansion import expansion_index, filtered_queries, score_sources, source_frame, verify_upstream
from gsearch.retrieval import BM25, Corpus


class OpenSourceExpansionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        path = Path(self.directory.name) / "documents.json"
        path.write_text(json.dumps([
            {"doc_id": "a", "code": "00000", "title": "Oxygen", "sentences": ["Cells need oxygen."]},
            {"doc_id": "b", "code": "00001", "title": "Water", "sentences": ["Water samples collected."]}]), encoding="utf-8")
        self.corpus = Corpus(path)
        self.scored = [{"doc_id": "a", "queries": ["low", "edge"], "scores": [0.2, 0.8]},
                       {"doc_id": "b", "queries": ["other"], "scores": [0.1]}]

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_real_upstream_files_match_commit_and_java_stays_off(self) -> None:
        self.assertEqual(verify_upstream()["direct_reuse"]["repository"], "terrierteam/pyterrier_doc2query")
        self.assertFalse(pt.java.started())

    def test_upstream_threshold_includes_equality_and_can_empty_a_document(self) -> None:
        original = copy.deepcopy(self.scored)
        actual = filtered_queries(self.corpus, self.scored, 0.8)
        self.assertEqual(actual, {"a": ["edge"], "b": []})
        self.assertEqual(self.scored, original)

    def test_upstream_scorer_preserves_document_and_query_group_alignment(self) -> None:
        class ContractOnlyModel:
            def logits(self, first: list, second: list) -> np.ndarray:
                return np.array([[{"low": 0.2, "edge": 0.8, "other": 0.1}[q]] for q in first])
        records = [{"doc_id": r["doc_id"], "queries": r["queries"]} for r in reversed(self.scored)]
        result = score_sources(self.corpus, records, ContractOnlyModel())
        self.assertEqual(result, self.scored)

    def test_invalid_score_alignment_and_nan_are_rejected(self) -> None:
        for values in ([0.2], [float("nan"), 0.8]):
            bad = copy.deepcopy(self.scored)
            bad[0]["scores"] = values
            with self.assertRaises(ValueError):
                filtered_queries(self.corpus, bad, 0.5)

    def test_partial_documents_and_embedded_query_newlines_are_rejected(self) -> None:
        records = [{"doc_id": r["doc_id"], "queries": r["queries"]} for r in self.scored]
        with self.assertRaises(ValueError):
            source_frame(self.corpus, records[:-1])
        records[0]["queries"] = ["bad\nambiguous"]
        with self.assertRaises(ValueError):
            source_frame(self.corpus, records)

    def test_expansion_retrieves_without_rewriting_original_evidence(self) -> None:
        original = copy.deepcopy(self.corpus.documents)
        baseline = BM25(self.corpus)
        self.assertEqual(baseline.search("quasar"), [])
        baseline.db.close()
        index, _ = expansion_index(self.corpus, {"a": ["quasar sentinel"], "b": []})
        session = EvidenceSession(self.corpus, {"expanded": index})
        session.search("quasar", "expanded", 2)
        session.read_document("a")
        self.assertIn("error", session.record("a", [1], "SUPPORT"))
        recorded = session.record("a", [0], "SUPPORT")
        self.assertEqual(recorded["quotes"], ["Cells need oxygen."])
        self.assertEqual(self.corpus.documents, original)
        index.db.close()


if __name__ == "__main__":
    unittest.main()
