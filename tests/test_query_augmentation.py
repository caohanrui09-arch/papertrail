import json
from pathlib import Path
import tempfile
import unittest

from gsearch.query_augmentation import accepted_queries
from gsearch.retrieval import Corpus
from gsearch.train_query_aug import PairedSampler


class QueryAugmentationTests(unittest.TestCase):
    def test_candidates_are_weak_labels_not_gold_filtered(self) -> None:
        document = {"doc_id": "a", "title": "Oxygen", "sentences": ["Oxygen sustains cells."]}
        result = accepted_queries(document, ["  Why cells?  ", "why   CELLS?"])
        self.assertEqual(result["raw_candidates"], ["  Why cells?  ", "why   CELLS?"])
        self.assertEqual(result["queries"], ["Why cells?"])
        self.assertFalse(result["fallback"])
        unrelated = accepted_queries(document, ["a completely unrelated question"])
        self.assertEqual(unrelated["queries"], ["a completely unrelated question"])

    def test_empty_generation_uses_explicit_corpus_only_fallback(self) -> None:
        result = accepted_queries({"doc_id": "a", "title": "  Cells ", "sentences": []}, ["", " "])
        self.assertTrue(result["fallback"])
        self.assertEqual(result["queries"], ["Cells"])


class PairedSamplerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        path = Path(self.directory.name) / "documents.json"
        docs = [{"doc_id": str(i), "code": f"title | {i:05d}", "title": f"Paper {i}",
                 "sentences": [f"Sentence {i}"]} for i in range(3)]
        path.write_text(json.dumps(docs), encoding="utf-8")
        self.corpus = Corpus(path)
        self.claims = [{"id": 7, "claim": "Original claim", "evidence": {"0": []}}]
        self.records = [{"doc_id": str(i), "queries": [f"query {i} a", f"query {i} b"]} for i in range(3)]

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_matched_samplers_keep_gold_inputs_and_every_target_identical(self) -> None:
        a = PairedSampler(self.corpus, self.claims, self.records, "control")
        b = PairedSampler(self.corpus, self.claims, self.records, "qg")
        synthetic = set()
        for _ in range(100):
            left, right = a.sample(8), b.sample(8)
            self.assertEqual([p[1] for p in left], [p[1] for p in right])
            for x, y in zip(left, right):
                if x[0].startswith("search:"):
                    self.assertEqual(x, y)
                else:
                    self.assertTrue(y[0].startswith("search: query"))
                    synthetic.add(y[0])
        self.assertEqual(a.schedule.hexdigest(), b.schedule.hexdigest())
        self.assertEqual(a.visits, b.visits)
        self.assertEqual(a.counts["gold_query"], b.counts["gold_query"])
        self.assertEqual(a.counts["index"], b.counts["synthetic_query"])
        self.assertEqual(len(synthetic), 6)

    def test_partial_or_duplicate_corpus_coverage_is_rejected(self) -> None:
        for records in (self.records[:-1], self.records + [self.records[0]],
                        [{**self.records[0], "queries": []}, *self.records[1:]]):
            with self.assertRaises(ValueError):
                PairedSampler(self.corpus, self.claims, records, "qg")


if __name__ == "__main__":
    unittest.main()
