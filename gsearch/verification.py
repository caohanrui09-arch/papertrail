"""Budgeted document reranking, sentence-group proposals and independent NLI checks."""
from itertools import combinations
import hashlib
import json
import math
from pathlib import Path

from .evidence_models import NLIModel, RelevanceModel
from .retrieval import Corpus


class RerankedRetriever:
    name = "hybrid_cross_encoder"

    def __init__(self, corpus: Corpus, retriever: object, relevance: RelevanceModel, pool_size: int = 10):
        self.corpus, self.retriever, self.relevance = corpus, retriever, relevance
        self.pool_size = pool_size

    def search(self, query: str, k: int = 10) -> list[dict]:
        if type(k) is not int or not 1 <= k <= self.pool_size:
            raise ValueError("Requested result size exceeds reranking pool")
        hits = [h for h in self.retriever.search(query, self.pool_size) if h["doc_id"] in self.corpus.by_id]
        passages = [self.corpus.by_id[h["doc_id"]]["title"] + " " +
                    " ".join(self.corpus.by_id[h["doc_id"]]["sentences"]) for h in hits]
        scores = self.relevance.score(query, passages)
        rows = [{**hit, "retrieval_score": hit["score"], "score": score, "relevance_score": score}
                for hit, score in zip(hits, scores)]
        return sorted(rows, key=lambda row: -row["score"])[:k]


def choose_evidence(candidates: list[dict], config: dict) -> dict:
    selected = []
    for document in candidates:
        if document["relevance_score"] < config["min_doc_score"]:
            continue
        accepted = []
        groups = document["groups"]
        if config.get("rationale_model"):
            selected_ids = sorted([r["sentence_id"] for r in document["sentence_relevance"]
                                   if r["probability"] >= config["rationale_threshold"]][:3])
            groups = [g for g in groups if g["sentence_ids"] == selected_ids] if selected_ids else []
        for group in groups:
            probabilities = group["probabilities"]
            stance = max(("SUPPORT", "CONTRADICT"), key=lambda label: probabilities[label])
            confidence = probabilities[stance]
            if (confidence >= config["min_confidence"]
                    and confidence - probabilities["INSUFFICIENT"] >= config["neutral_margin"]):
                accepted.append({"doc_id": document["doc_id"], "sentence_ids": group["sentence_ids"],
                                 "stance": stance, "confidence": confidence,
                                 "relevance_score": document["relevance_score"],
                                 "probabilities": probabilities,
                                 "utility": confidence - 0.01 * (len(group["sentence_ids"]) - 1)})
        if accepted:
            selected.append(max(accepted, key=lambda group: group["utility"]))
    selected.sort(key=lambda row: -row["utility"])
    stances = {row["stance"] for row in selected}
    return {"verdict": next(iter(stances)) if len(stances) == 1 else "INSUFFICIENT",
            "conflicting_evidence": len(stances) > 1, "evidence": selected,
            "assessment_kind": "independent_model_prediction_not_ground_truth"}


class EvidenceVerifier:
    def __init__(self, corpus: Corpus, relevance: RelevanceModel, nli: NLIModel,
                 config: dict | None = None, max_documents: int = 3, top_sentences: int = 5,
                 rationale: RelevanceModel | None = None):
        self.corpus, self.relevance, self.nli = corpus, relevance, nli
        self.max_documents, self.top_sentences = max_documents, top_sentences
        self.rationale = rationale
        self.config = config or {"min_doc_score": 0.0, "min_confidence": 0.85, "neutral_margin": 0.2}
        if max_documents < 1 or top_sentences < 1:
            raise ValueError("Evidence budgets must be positive")
        if "corpus_fingerprint" in self.config and self.config["corpus_fingerprint"] != corpus.fingerprint:
            raise ValueError("Verifier configuration has a different corpus")
        self.cache: dict[tuple[str, tuple[str, ...]], list[dict]] = {}

    def candidates(self, claim: str, doc_ids: list[str]) -> list[dict]:
        ids = list(dict.fromkeys(doc_ids))
        if not ids or len(ids) > 10 or any(doc_id not in self.corpus.by_id for doc_id in ids):
            raise ValueError("Expected 1-10 known document IDs")
        key = (claim, tuple(ids))
        if key in self.cache:
            return self.cache[key]
        passages = [self.corpus.by_id[doc]["title"] + " " + " ".join(self.corpus.by_id[doc]["sentences"]) for doc in ids]
        doc_scores = self.relevance.score(claim, passages)
        ranked = sorted(zip(ids, doc_scores), key=lambda pair: -pair[1])[:self.max_documents]
        output = []
        for doc_id, doc_score in ranked:
            sentences = self.corpus.by_id[doc_id]["sentences"]
            scores = (self.rationale or self.relevance).score(claim, sentences)
            best = sorted(range(len(sentences)), key=lambda i: -scores[i])[:self.top_sentences]
            probabilities_rationale = {i: 1 / (1 + math.exp(-max(-80, min(80, scores[i])))) for i in best}
            if self.rationale is None:
                groups = [sorted(group) for size in range(1, min(3, len(best)) + 1) for group in combinations(best, size)]
            else:
                groups = sorted({tuple(sorted([i for i in best if probabilities_rationale[i] >= threshold][:3]))
                                 for threshold in (0.3, 0.5, 0.7)} - {()})
                groups = [list(group) for group in groups]
            texts = [" ".join(sentences[i] for i in group) for group in groups]
            probabilities = self.nli.probabilities(texts, claim)
            output.append({"doc_id": doc_id, "relevance_score": doc_score,
                           "sentence_relevance": [{"sentence_id": i, "score": scores[i],
                                                   "probability": probabilities_rationale[i]} for i in best],
                           "groups": [{"sentence_ids": group, "probabilities": p}
                                      for group, p in zip(groups, probabilities)]})
        self.cache[key] = output
        return output

    def assess(self, claim: str, doc_ids: list[str]) -> dict:
        result = choose_evidence(self.candidates(claim, doc_ids), self.config)
        for entry in result["evidence"]:
            doc = self.corpus.by_id[entry["doc_id"]]
            entry["title"] = doc["title"]
            entry["quotes"] = [doc["sentences"][i] for i in entry["sentence_ids"]]
        return result

    def check_quote(self, claim: str, doc_id: str, sentence_ids: list[int], stance: str) -> dict:
        doc = self.corpus.by_id[doc_id]
        premise = " ".join(doc["sentences"][i] for i in sentence_ids)
        p = self.nli.probabilities([premise], claim)[0]
        doc_score = self.relevance.score(claim, [doc["title"] + " " + " ".join(doc["sentences"])])[0]
        verdict = max(("SUPPORT", "CONTRADICT"), key=lambda label: p[label])
        accepted = (stance == verdict and doc_score >= self.config["min_doc_score"]
                    and p[verdict] >= self.config["min_confidence"]
                    and p[verdict] - p["INSUFFICIENT"] >= self.config["neutral_margin"])
        expected = self.assess(claim, [doc_id])["evidence"]
        accepted = accepted and any(e["stance"] == stance and e["sentence_ids"] == sorted(set(sentence_ids))
                                    for e in expected)
        return {"accepted": accepted, "predicted_stance": verdict, "probabilities": p,
                "relevance_score": doc_score, "independent_model_checked": True,
                "selector_proposals": [{"sentence_ids": e["sentence_ids"], "stance": e["stance"]} for e in expected],
                "semantic_stance_verified": False}


def validate_frozen_assets(corpus: Corpus, config: dict) -> None:
    if config["corpus_fingerprint"] != corpus.fingerprint:
        raise ValueError("Verifier configuration has a different corpus")
    for key, expected in config.get("model_hashes", {}).items():
        weights = Path(config[key]) / "model.safetensors"
        if hashlib.file_digest(weights.open("rb"), "sha256").hexdigest() != expected:
            raise ValueError(f"Frozen {key} weights differ from the selected model")


def load_verifier(corpus: Corpus, config_path: Path) -> EvidenceVerifier:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    validate_frozen_assets(corpus, config)
    return EvidenceVerifier(corpus, RelevanceModel(Path(config["relevance_model"])),
                            NLIModel(Path(config["nli_model"])), config,
                            max_documents=config["max_documents"], top_sentences=config["top_sentences"],
                            rationale=RelevanceModel(Path(config["rationale_model"]), max_length=256)
                            if config.get("rationale_model") else None)
