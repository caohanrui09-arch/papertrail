from dataclasses import asdict
import unittest
from unittest.mock import patch

from gsearch.benchmark_bundles import claim_score, score_rollouts
from gsearch.budget_model import BudgetedToolModel, GenerationMeter
from gsearch.bundle_session import BundleBudget, BundleSession
from gsearch.bundle_tasks import construct_tasks


class Retriever:
    def search(self, query: str, k: int) -> list[dict]:
        prefix = "1" if "alpha" in query else "2"
        return [{"doc_id": prefix + str(i), "title": "test document", "score": 1} for i in range(k)]


class Verifier:
    def __init__(self) -> None:
        self.calls = []
        self.cache = {}
        self.foreign = False

    def assess(self, claim: str, ids: list[str]) -> dict:
        self.calls.append((claim, list(ids)))
        return {"evidence": [{"doc_id": "foreign" if self.foreign else doc, "sentence_ids": [0],
                              "stance": "CONTRADICT" if "alpha" in claim else "SUPPORT", "quotes": ["source"]}
                             for doc in ids]}


class BundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.verifier = Verifier()
        self.session = BundleSession({"A": "alpha claim", "B": "beta claim"},
                                     {"hybrid_checked": Retriever(), "bm25": Retriever()}, self.verifier)

    def test_task_construction_is_label_blind_and_has_no_reused_claims(self) -> None:
        claims = [{"id": i, "claim": f"Statement {i}", "evidence": {"10": [{"label": "SUPPORT", "sentences": [0]}]}}
                  for i in range(8)]
        public, gold = construct_tasks(claims, "dev", 17)
        reversed_labels = [{**c, "evidence": {}} for c in claims]
        self.assertEqual(public, construct_tasks(reversed_labels, "dev", 17)[0])
        ids = [c["source_claim_id"] for bundle in gold.values() for c in bundle.values()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(set(task) == {"task_id", "claims", "instruction"} for task in public))

    def test_evidence_retrieved_for_A_cannot_be_assessed_for_B(self) -> None:
        hits = self.session.search("A", "alpha", "hybrid_checked", 1)["hits"]
        self.assertIn("error", self.session.assess("B", [hits[0]["doc_id"]]))
        self.assertEqual(self.verifier.calls, [])

    def test_repeated_assessments_cost_the_same_shared_pair_budget(self) -> None:
        ids = [h["doc_id"] for h in self.session.search("A", "alpha", "hybrid_checked", 3)["hits"]]
        self.assertNotIn("error", self.session.assess("A", ids))
        self.assertNotIn("error", self.session.assess("A", ids))
        self.assertIn("error", self.session.assess("A", [ids[0]]))
        self.assertEqual(self.session.document_claim_pairs, 6)
        self.assertEqual(len(self.verifier.calls), 2)

    def test_shared_search_ceiling_is_enforced_before_retrieval(self) -> None:
        for _ in range(4):
            self.assertNotIn("error", self.session.search("A", "alpha", "bm25", 1))
        self.assertIn("error", self.session.search("B", "beta", "bm25", 1))
        self.assertEqual(self.session.searches, 4)

    def test_query_rewriting_cannot_change_the_checker_hypothesis(self) -> None:
        doc = self.session.search("A", "beta opposite wording", "bm25", 1)["hits"][0]["doc_id"]
        self.session.assess("A", [doc])
        self.assertEqual(self.verifier.calls[-1][0], "alpha claim")

    def test_original_query_handle_preserves_quotes_without_model_escaping(self) -> None:
        text = 'alpha claim with "quoted text" and \\ symbols'
        self.session.claims["A"] = text
        doc = self.session.search("A", "", "bm25", 1)["hits"][0]["doc_id"]
        self.session.assess("A", [doc])
        self.assertEqual(self.verifier.calls[-1][0], text)

    def test_final_answer_requires_both_claims_and_keeps_citations_scoped(self) -> None:
        for key, query in (("A", "alpha"), ("B", "beta")):
            doc = self.session.search(key, query, "bm25", 1)["hits"][0]["doc_id"]
            self.session.assess(key, [doc])
        answer = self.session.expected_answer()
        self.assertEqual(set(self.session.finalize(answer)), {"A", "B"})
        with self.assertRaises(ValueError):
            self.session.finalize({"A": answer["A"]})
        answer["B"]["citations"] = answer["A"]["citations"]
        with self.assertRaises(ValueError):
            self.session.finalize(answer)

    def test_foreign_verifier_source_is_rejected(self) -> None:
        self.verifier.foreign = True
        doc = self.session.search("A", "alpha", "bm25", 1)["hits"][0]["doc_id"]
        self.assertIn("error", self.session.assess("A", [doc]))
        self.assertNotIn("A", self.session.checked)

    def test_llm_cumulative_limits_reject_before_an_extra_forward(self) -> None:
        meter = GenerationMeter(BundleBudget(max_steps=2, input_tokens=100, output_tokens=17))
        self.assertEqual(meter.reserve_input(60), 17)
        meter.record_output(10)
        with self.assertRaises(ValueError):
            meter.reserve_input(50)
        self.assertEqual(meter.calls, 1)
        self.assertEqual(meter.reserve_input(20), 7)
        meter.record_output(7)
        with self.assertRaises(ValueError):
            meter.reserve_input(0)
        self.assertEqual(meter.input_tokens, 80)
        self.assertEqual(meter.output_tokens, 17)

    def test_actual_generation_argument_is_clipped_to_remaining_tokens(self) -> None:
        import torch
        model = object.__new__(BudgetedToolModel)
        model.reset_budget(BundleBudget(output_tokens=17))
        model.meter.output_tokens = 15
        with patch("gsearch.local_model.LocalToolModel._prepare_completion_args",
                   return_value={"inputs": torch.tensor([[1, 2]]), "max_new_tokens": 160}):
            self.assertEqual(model._prepare_completion_args()["max_new_tokens"], 2)

    def test_no_published_answer_cannot_receive_abstention_credit(self) -> None:
        gold = {"evidence": {}}
        self.assertFalse(claim_score(None, gold)["success"])
        self.assertTrue(claim_score({"verdict": "INSUFFICIENT", "citations": [], "evidence": []}, gold)["success"])

    def test_over_budget_result_is_not_a_success_even_with_correct_verdicts(self) -> None:
        prediction = {"verdict": "INSUFFICIENT", "citations": [], "evidence": []}
        report = {"task_id": "task", "checked_results": {"A": prediction, "B": prediction},
                  "completed_protocol": True, "seconds": 1, "classifier_work": {}, "llm_metadata": {},
                  "tool_usage": {"searches": 2, "assessments": 2, "document_claim_pairs": 7,
                                 "generative_searches": 2, "ceilings": asdict(BundleBudget())}}
        score = score_rollouts([report], {"task": {"A": {"evidence": {}}, "B": {"evidence": {}}}})
        self.assertEqual(score["successful_tasks"], 0)
        self.assertEqual(score["budget_violations"], 1)


if __name__ == "__main__":
    unittest.main()
