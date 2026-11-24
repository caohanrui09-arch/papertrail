import json
from pathlib import Path
import tempfile
import unittest

from gsearch.agent import EvidenceSession, run_agent
from gsearch.evaluate_verifier import score_predictions
from gsearch.retrieval import BM25, Corpus
from gsearch.verification import EvidenceVerifier, choose_evidence, validate_frozen_assets


CONFIG = {"min_doc_score": 0, "min_confidence": 0.8, "neutral_margin": 0.2}


class VerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        path = Path(self.directory.name) / "documents.json"
        path.write_text(json.dumps([{"doc_id": "101", "code": "00000", "title": "Oxygen cells",
                                     "sentences": ["An experiment was performed.", "Oxygen reduced growth.",
                                                   "This contradicts an increase in growth."]}]), encoding="utf-8")
        self.corpus = Corpus(path)

        class Verifier:
            config = CONFIG

            def assess(inner, claim: str, docs: list[str]) -> dict:
                return {"verdict": "CONTRADICT", "evidence": [{"doc_id": "101", "title": "Oxygen cells",
                        "sentence_ids": [1, 2], "stance": "CONTRADICT", "confidence": 0.9,
                        "quotes": ["Oxygen reduced growth.", "This contradicts an increase in growth."]}]}

            def check_quote(inner, claim: str, doc: str, ids: list[int], stance: str) -> dict:
                return {"accepted": stance == "CONTRADICT" and ids == [1, 2],
                        "probabilities": {"CONTRADICT": 0.9, "SUPPORT": 0.01, "INSUFFICIENT": 0.09}}

        self.session = EvidenceSession(self.corpus, {"bm25": BM25(self.corpus)},
                                       verifier=Verifier(), claim="Oxygen increases growth.")

    def tearDown(self) -> None:
        self.session.retrievers["bm25"].db.close()
        self.directory.cleanup()

    def test_checked_answer_cannot_reverse_stance_or_invent_citations(self) -> None:
        self.session.search("oxygen", "bm25", 1)
        assessment = self.session.verify_documents(["101"])
        self.assertEqual(assessment["citations"], ["101:1,2"])
        with self.assertRaises(ValueError):
            self.session.validate_checked_answer({"verdict": "SUPPORT", "citations": ["101:1,2"]})
        with self.assertRaises(ValueError):
            self.session.validate_checked_answer({"verdict": "CONTRADICT", "citations": ["999:0"]})
        answer = self.session.validate_checked_answer({"verdict": "CONTRADICT", "citations": ["101:1,2"]})
        self.assertEqual(answer["claim"], "Oxygen increases growth.")
        self.assertFalse(answer["evidence"][0]["semantic_stance_verified"])

    def test_verification_shares_read_budget_and_deduplicates_sources(self) -> None:
        self.assertIn("error", self.session.verify_documents(["101"]))
        self.session.search("oxygen", "bm25", 1)
        self.assertNotIn("error", self.session.verify_documents(["101", "101"]))
        self.assertEqual(self.session.read_count, 1)
        self.assertEqual(len(self.session.evidence), 1)
        self.assertIn("error", self.session.verify_documents(["101"]))

    def test_manual_record_cannot_bypass_independent_stance_or_selector(self) -> None:
        self.session.search("oxygen", "bm25", 1)
        self.session.read_document("101")
        self.assertIn("error", self.session.record("101", [1], "SUPPORT"))
        self.assertEqual(self.session.evidence, [])
        self.assertNotIn("error", self.session.record("101", [1, 2], "CONTRADICT"))

    def test_weak_neutral_or_irrelevant_sources_are_not_accepted(self) -> None:
        document = {"doc_id": "101", "relevance_score": 5,
                    "groups": [{"sentence_ids": [1], "probabilities":
                                {"SUPPORT": 0.1, "CONTRADICT": 0.1, "INSUFFICIENT": 0.8}}]}
        self.assertEqual(choose_evidence([document], CONFIG)["evidence"], [])
        document["groups"][0]["probabilities"] = {"SUPPORT": 0.9, "CONTRADICT": 0.05, "INSUFFICIENT": 0.05}
        document["relevance_score"] = -1
        self.assertEqual(choose_evidence([document], CONFIG)["evidence"], [])

    def test_complete_multisentence_rationale_and_label_are_both_required(self) -> None:
        probabilities = {"SUPPORT": 0.01, "CONTRADICT": 0.98, "INSUFFICIENT": 0.01}
        gold = [{"id": 1, "evidence": {"101": [{"sentences": [1, 2], "label": "CONTRADICT"}]}}]
        rows = [{"claim_id": 1, "candidates": [{"doc_id": "101", "relevance_score": 5,
                  "groups": [{"sentence_ids": [1], "probabilities": probabilities}]}]}]
        self.assertEqual(score_predictions(rows, gold, CONFIG)["abstract_with_stance"]["correct"], 0)
        rows[0]["candidates"][0]["groups"][0]["sentence_ids"] = [1, 2]
        self.assertEqual(score_predictions(rows, gold, CONFIG)["abstract_with_stance"]["correct"], 1)

    def test_rationale_threshold_selects_model_rank_before_restoring_source_order(self) -> None:
        document = {"doc_id": "101", "relevance_score": 5,
                    "sentence_relevance": [{"sentence_id": i, "probability": 0.9} for i in [8, 2, 7, 0]],
                    "groups": [{"sentence_ids": [2, 7, 8], "probabilities":
                                {"SUPPORT": 0.01, "CONTRADICT": 0.98, "INSUFFICIENT": 0.01}}]}
        result = choose_evidence([document], {**CONFIG, "rationale_model": "selector", "rationale_threshold": 0.5})
        self.assertEqual(result["evidence"][0]["sentence_ids"], [2, 7, 8])

    def test_claim_cannot_be_silently_changed_for_the_checker(self) -> None:
        with self.assertRaises(ValueError):
            run_agent(self.session, "Oxygen reduces growth.", object())

    def test_configuration_must_match_the_corpus(self) -> None:
        with self.assertRaises(ValueError):
            EvidenceVerifier(self.corpus, object(), object(), {"corpus_fingerprint": "another"})

    def test_changed_model_weights_cannot_reuse_frozen_evaluation_config(self) -> None:
        model = Path(self.directory.name) / "model"
        model.mkdir()
        (model / "model.safetensors").write_bytes(b"changed weights")
        with self.assertRaisesRegex(ValueError, "weights differ"):
            validate_frozen_assets(self.corpus, {"corpus_fingerprint": self.corpus.fingerprint,
                                   "nli_model": str(model), "model_hashes": {"nli_model": "previous hash"}})

    def test_real_framework_rejects_a_reversed_final_answer_before_accepting_correct_one(self) -> None:
        from smolagents import Model
        from smolagents.models import ChatMessage, MessageRole

        class ScriptedModel(Model):
            def __init__(inner) -> None:
                super().__init__(model_id="scripted_checked_contract")
                inner.calls = iter([
                    {"name": "search_documents", "arguments": {"query": "oxygen", "method": "bm25", "k": 1}},
                    {"name": "verify_documents", "arguments": {"doc_ids": ["101"]}},
                    {"name": "final_answer", "arguments": {"answer": {"verdict": "SUPPORT", "citations": ["101:1,2"]}}},
                    {"name": "final_answer", "arguments": {"answer": {"verdict": "CONTRADICT", "citations": ["101:1,2"]}}}])

            def generate(inner, messages: list, **kwargs: object) -> ChatMessage:
                return ChatMessage(role=MessageRole.ASSISTANT, content=json.dumps(next(inner.calls)))

        result = run_agent(self.session, "Oxygen increases growth.", ScriptedModel())
        self.assertTrue(result["completed_protocol"])
        self.assertEqual(result["checked_answer"]["verdict"], "CONTRADICT")
        self.assertEqual(result["answer_status"], "independently_checked_prediction")
        self.assertTrue(any(step.get("error") for step in result["agent_steps"]))


if __name__ == "__main__":
    unittest.main()
