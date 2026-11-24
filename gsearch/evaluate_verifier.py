"""Cache predictions without gold, tune thresholds on tuning only, score held-out dev."""
import argparse
from itertools import product
import json
from pathlib import Path
import time

import torch

from .data import write_json
from .evidence_models import NLIModel, RelevanceModel
from .retrieval import BM25, Corpus, GenerativeRetriever, Hybrid
from .verification import EvidenceVerifier, RerankedRetriever, choose_evidence, validate_frozen_assets


def f1_counts(correct: int, predicted: int, gold: int) -> dict:
    precision = correct / predicted if predicted else 0.0
    recall = correct / gold if gold else 0.0
    return {"correct": correct, "predicted": predicted, "gold": gold, "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0}


def score_predictions(rows: list[dict], claims: list[dict], config: dict) -> dict:
    golds = {c["id"]: c for c in claims}
    correct_docs = correct_labeled = predicted_docs = gold_docs = 0
    correct_sentences = predicted_sentences = gold_sentences = 0
    no_evidence = correct_abstentions = candidate_gold_docs = 0
    cases = []
    for row in rows:
        gold = golds[row["claim_id"]]["evidence"]
        result = choose_evidence(row["candidates"], config)
        evidence = result["evidence"]
        gold_docs += len(gold)
        predicted_docs += len(evidence)
        if not gold:
            no_evidence += 1
            correct_abstentions += not evidence and result["verdict"] == "INSUFFICIENT"
        per_case = 0
        for candidate in row["candidates"]:
            if any(set(r["sentences"]).issubset(g["sentence_ids"])
                   for r in gold.get(candidate["doc_id"], []) for g in candidate["groups"]):
                candidate_gold_docs += 1
        for rationales in gold.values():
            gold_sentences += len({i for r in rationales for i in r["sentences"]})
        for entry in evidence:
            sentence_ids = set(entry["sentence_ids"][:3])
            predicted_sentences += len(sentence_ids)
            rationales = gold.get(entry["doc_id"], [])
            complete = [r for r in rationales if set(r["sentences"]).issubset(sentence_ids)]
            correct_docs += bool(complete)
            labeled = [r for r in complete if r["label"] == entry["stance"]]
            correct_labeled += bool(labeled)
            per_case += bool(labeled)
            correct_sentences += len({i for r in labeled for i in r["sentences"]} & sentence_ids)
        cases.append({"claim_id": row["claim_id"], "verdict": result["verdict"],
                      "evidence": evidence, "gold_document_count": len(gold), "correct_labeled_documents": per_case})
    return {"queries": len(rows), "abstract_selection": f1_counts(correct_docs, predicted_docs, gold_docs),
            "abstract_with_stance": f1_counts(correct_labeled, predicted_docs, gold_docs),
            "sentence_with_stance": f1_counts(correct_sentences, predicted_sentences, gold_sentences),
            "candidate_rationale_doc_coverage": candidate_gold_docs / gold_docs if gold_docs else None,
            "no_evidence_queries": no_evidence, "correct_abstentions": correct_abstentions,
            "no_evidence_abstention_rate": correct_abstentions / no_evidence if no_evidence else None,
            "cases": cases}


def calibrate(rows: list[dict], claims: list[dict], base: dict) -> tuple[dict, list[dict]]:
    trials = []
    rationale_thresholds = [0.3, 0.5, 0.7] if base.get("rationale_model") else [None]
    for doc_score, confidence, margin, rationale_threshold in product([-3.0, 0.0, 3.0], [0.6, 0.75, 0.85, 0.95],
                                                                     [0.1, 0.2], rationale_thresholds):
        config = {**base, "min_doc_score": doc_score, "min_confidence": confidence, "neutral_margin": margin}
        if rationale_threshold is not None:
            config["rationale_threshold"] = rationale_threshold
        score = score_predictions(rows, claims, config)
        trials.append({"config": config, "abstract_with_stance": score["abstract_with_stance"],
                       "abstract_selection": score["abstract_selection"],
                       "no_evidence_abstention_rate": score["no_evidence_abstention_rate"]})
    best = max(trials, key=lambda t: (t["abstract_with_stance"]["f1"], t["abstract_selection"]["f1"],
                                     t["no_evidence_abstention_rate"] or 0, t["config"]["min_confidence"]))
    return best["config"], trials


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("data/prepared"))
    parser.add_argument("--checkpoint", type=Path, default=Path("runs/t5-dsi-4000-seed42"))
    parser.add_argument("--relevance-model", type=Path, default=Path(".cache/models/ms-marco-MiniLM-L6-v2"))
    parser.add_argument("--nli-model", type=Path, required=True)
    parser.add_argument("--rationale-model", type=Path)
    parser.add_argument("--split", choices=["tuning", "dev"], default="tuning")
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.calibrate and args.split != "tuning":
        parser.error("Threshold selection is allowed only on tuning")
    if not args.calibrate and args.config is None:
        parser.error("Frozen --config required for evaluation")
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Refusing to overwrite verification evaluation")
    args.output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(4)
    corpus = Corpus(args.data / "documents.json")
    claims = json.loads((args.data / f"{args.split}.json").read_text(encoding="utf-8"))
    relevance = RelevanceModel(args.relevance_model)
    nli = NLIModel(args.nli_model)
    verifier = EvidenceVerifier(corpus, relevance, nli,
                                rationale=RelevanceModel(args.rationale_model, max_length=256) if args.rationale_model else None)
    hybrid = Hybrid(BM25(corpus), GenerativeRetriever(corpus, args.checkpoint))
    reranked = RerankedRetriever(corpus, hybrid, relevance)
    base = {"corpus_fingerprint": corpus.fingerprint, "relevance_model": str(args.relevance_model),
            "nli_model": str(args.nli_model), "max_documents": 3, "top_sentences": 5,
            "retrieval_checkpoint": str(args.checkpoint), "retrieval_pool": 10,
            "max_evidence_sentences": 3, "selection_split": "tuning"}
    if args.rationale_model:
        base["rationale_model"] = str(args.rationale_model)
    if args.config:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        for key in ("corpus_fingerprint", "relevance_model", "nli_model", "retrieval_checkpoint", "rationale_model"):
            if config.get(key) != base.get(key):
                raise ValueError(f"Frozen configuration differs on {key}")
        validate_frozen_assets(corpus, config)
    else:
        config = None
    rows = []
    start = time.perf_counter()
    for index, claim in enumerate(claims):
        # Only text and query ID enter inference; no evidence or label enters the models.
        query_start = time.perf_counter()
        hits = reranked.search(claim["claim"], 10)
        candidates = verifier.candidates(claim["claim"], [h["doc_id"] for h in hits])
        rows.append({"claim_id": claim["id"], "query": claim["claim"], "reranked_hits": hits,
                     "candidates": candidates, "seconds": time.perf_counter() - query_start})
        if index == 0 or (index + 1) % 25 == 0:
            print(json.dumps({"queries": index + 1, "seconds": time.perf_counter() - start}), flush=True)
    write_json(args.output / "raw_predictions.json", {"split": args.split, "base": base, "queries": rows})
    if args.calibrate:
        config, trials = calibrate(rows, claims, base)
        write_json(args.output / "calibration_trials.json", trials)
    write_json(args.output / "config.json", config)
    result = score_predictions(rows, claims, config)
    result.update({"split": args.split, "config": config, "seconds": time.perf_counter() - start,
                   "metric_note": "SciFact-style counts; at most three predicted sentences, not an official leaderboard submission"})
    write_json(args.output / "scores.json", result)
    print(json.dumps({key: value for key, value in result.items() if key != "cases"}, indent=2))


if __name__ == "__main__":
    main()
