"""Predeclared tuning gate for matched full/short raw-token training."""
import argparse
import json
from pathlib import Path
import time

import torch

from .data import write_json
from .evaluate import evaluate
from .identifiers import sha256
from .prefix_decoder import PrefixIndex, PrefixRetriever, VENDOR
from .retrieval import BM25, Corpus, GenerativeRetriever
from .train_query_aug import checkpoint_hashes
from .train_target_alignment import (BASE, DATA, ROOT, RUNS, TARGETS, TRAINING, engine_state, read)


GATE = {"quality_ndcg_gain": 0.01, "max_recall_drop": 0.01,
        "max_uncovered_recall_drop": 0.02, "cost_max_ndcg_drop": 0.01,
        "cost_max_returned_token_ratio": 0.75, "cost_max_latency_ratio": 0.85}


def state() -> dict:
    return {"base_assets": checkpoint_hashes(BASE), "engine": engine_state(),
            "data": {p.name: sha256(p) for p in DATA.glob("*.json")},
            "targets": {p.name: sha256(p) for p in TARGETS.glob("*.json")},
            "code": {p: sha256(Path("gsearch") / p) for p in (
                "train_target_alignment.py", "benchmark_target_alignment.py", "prefix_decoder.py",
                "retrieval.py", "evaluate.py", "train.py", "train_query_aug.py")},
            "vendor": {p.name: sha256(p) for p in VENDOR.iterdir() if p.is_file()},
            "upstream_audit_sha256": sha256(ROOT / "upstream-audit.json")}


def check_plan() -> dict:
    plan = read(ROOT / "plan.json")
    if plan["state"] != state() or plan["training"] != TRAINING or plan["gate"] != GATE:
        raise ValueError("Matched-training protocol drift")
    return plan


def weights() -> dict:
    return {m: checkpoint_hashes(p) for m, p in RUNS.items()}


def group_summary(result: dict) -> dict:
    supervised = {d for c in read(DATA / "train.json") for d in c["evidence"]}
    groups = {}
    for label, covered in (("all_gold_supervised", True), ("some_gold_not_supervised", False)):
        rows = [r for r in result["queries"] if set(r["relevant"]).issubset(supervised) == covered]
        groups[label] = {"queries": len(rows), **{k: sum(r[k] for r in rows)/len(rows) if rows else None
                                                    for k in ("recall", "mrr", "ndcg")}}
    return groups


def gate(full: dict, short: dict) -> dict:
    if (not full["queries"] or [q["claim_id"] for q in full["queries"]] !=
            [q["claim_id"] for q in short["queries"]]):
        raise ValueError("Gate requires paired complete tuning outputs")
    f, s = full["summary"], short["summary"]
    ndcg = s["ndcg@10"] - f["ndcg@10"]
    recall = s["recall@10"] - f["recall@10"]
    uncovered = short["groups"]["some_gold_not_supervised"]["recall"] - full["groups"]["some_gold_not_supervised"]["recall"]
    token_ratio = short["cost"]["mean_returned_tokens"] / full["cost"]["mean_returned_tokens"]
    latency_ratio = s["mean_seconds"] / f["mean_seconds"]
    guarded = recall >= -GATE["max_recall_drop"] and uncovered >= -GATE["max_uncovered_recall_drop"]
    quality_pass = guarded and ndcg >= GATE["quality_ndcg_gain"]
    cost_pass = (guarded and ndcg >= -GATE["cost_max_ndcg_drop"] and
                 token_ratio <= GATE["cost_max_returned_token_ratio"] and latency_ratio <= GATE["cost_max_latency_ratio"])
    return {"passed": quality_pass or cost_pass, "quality_route_passed": quality_pass,
            "cost_route_passed": cost_pass, "quality_guards_passed": guarded,
            "short_minus_full": {"ndcg": ndcg, "recall": recall, "uncovered_recall": uncovered},
            "short_over_full": {"returned_tokens": token_ratio, "mean_seconds": latency_ratio},
            "interpretation": "operational pilot thresholds, not a statistical noninferiority test"}


def evaluate_split(split: str) -> None:
    if any((ROOT / f"{m}-{split}.json").exists() for m in (*RUNS, "bm25")):
        raise ValueError("Refusing to overwrite raw evaluation")
    corpus, claims = Corpus(DATA / "documents.json"), read(DATA / f"{split}.json")
    lexical = BM25(corpus)
    baseline = evaluate(lexical, claims, 10)
    baseline.update({"method": "bm25", "split": split, "groups": group_summary(baseline)})
    write_json(ROOT / f"bm25-{split}.json", baseline)
    lexical.db.close()
    # Construct both models before timing. Alternate order per query to reduce order bias.
    retrievers = {}
    for mode in RUNS:
        neural = GenerativeRetriever(corpus, RUNS[mode], 10)
        index = PrefixIndex(corpus, neural.tokenizer, mode == "short")
        if index.aliases != read(TARGETS / f"{mode}.json")["aliases"]:
            raise ValueError("Training/evaluation raw token targets differ")
        retrievers[mode] = PrefixRetriever(neural, index, 10)
        retrievers[mode].search(claims[0]["claim"], 10)  # one excluded warmup each
    from .evaluate import metrics
    rows, work = {m: [] for m in RUNS}, {m: [] for m in RUNS}
    judged = [c for c in claims if c["evidence"]]
    for i, claim in enumerate(judged):
        for mode in (("full", "short") if i % 2 == 0 else ("short", "full")):
            retriever = retrievers[mode]
            started = time.perf_counter()
            hits = retriever.search(claim["claim"], 10)
            seconds = time.perf_counter() - started
            ids = [r["doc_id"] for r in hits]
            rows[mode].append({"claim_id": claim["id"], "query": claim["claim"],
                "relevant": sorted(claim["evidence"]), "predictions": hits, "seconds": seconds,
                **metrics(ids, set(claim["evidence"]), 10), "valid_slots": sum(d is not None for d in ids),
                "unique_slots": len({d for d in ids if d is not None})})
            work[mode].append(retriever.receipts[-1])
        if (i+1) % 10 == 0:
            print(json.dumps({"split": split, "paired_queries": i+1, "total": len(judged)}), flush=True)
    for mode in RUNS:
        count = len(rows[mode])
        summary = {k+"@10": sum(r[k] for r in rows[mode])/count for k in ("recall", "hit", "mrr", "ndcg")}
        summary.update({"judged_queries": count, "no_evidence_queries_excluded": len(claims)-count,
                        "valid_slot_rate": sum(r["valid_slots"] for r in rows[mode])/(count*10),
                        "unique_slot_rate": sum(r["unique_slots"] for r in rows[mode])/(count*10),
                        "mean_seconds": sum(r["seconds"] for r in rows[mode])/count})
        result = {"method": mode, "split": split, "k": 10, "beam": 10, "summary": summary,
                  "queries": rows[mode], "decode_work": work[mode], "tree": retrievers[mode].index.stats,
                  "plan_sha256": sha256(ROOT / "plan.json"),
                  "timing": "batch1, alternating per-query method order, excluded warmup; both models resident",
                  "cost": {"mean_returned_tokens": sum(sum(r["returned_alias_tokens_including_eos"]) for r in work[mode])/(count*10),
                           "mean_generation_steps": sum(r["generation_steps"] for r in work[mode])/count}}
        result["groups"] = group_summary(result)
        write_json(ROOT / f"{mode}-{split}.json", result)
        print(json.dumps({"split": split, "method": mode, "summary": summary, "cost": result["cost"]}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("plan", "tuning", "gate", "dev"), required=True)
    args = parser.parse_args()
    torch.set_num_threads(4)
    if args.phase == "plan":
        if (ROOT / "plan.json").exists() or any(p.exists() for p in RUNS.values()):
            raise ValueError("Plan must precede training")
        write_json(ROOT / "plan.json", {"frozen_before_training": True, "training": TRAINING,
              "state": state(), "gate": GATE, "decode": {"beam": 10, "k": 10, "length_penalty": 1.0},
              "gate_rule": "quality route OR cost route, both with overall/uncovered recall guards",
              "if_failed": "stop route; do not evaluate dev", "if_passed": "freeze then evaluate both models on dev",
              "scope": "same steps/examples/order; target token counts differ, not equal FLOPs; public dev reused"})
        return
    check_plan()
    if args.phase == "tuning":
        if (ROOT / "trained-before-tuning.json").exists():
            raise ValueError("Training freeze already exists")
        write_json(ROOT / "trained-before-tuning.json", {"weights": weights(), "plan_sha256": sha256(ROOT / "plan.json")})
        evaluate_split("tuning")
        return
    trained = read(ROOT / "trained-before-tuning.json")
    if trained["weights"] != weights() or trained["plan_sha256"] != sha256(ROOT / "plan.json"):
        raise ValueError("Trained model freeze drift")
    if args.phase == "gate":
        if (ROOT / "tuning-decision.json").exists():
            raise ValueError("Refusing to overwrite gate decision")
        decision = gate(read(ROOT / "full-tuning.json"), read(ROOT / "short-tuning.json"))
        decision.update({"tuning_hashes": {m: sha256(ROOT / f"{m}-tuning.json") for m in (*RUNS, "bm25")},
                         "plan_sha256": sha256(ROOT / "plan.json"), "weights": weights(), "made_before_dev": True})
        write_json(ROOT / "tuning-decision.json", decision)
        if decision["passed"]:
            write_json(ROOT / "locked-before-dev.json", decision)
        print(json.dumps(decision), flush=True)
        return
    decision = read(ROOT / "locked-before-dev.json")
    if (not decision["passed"] or decision != read(ROOT / "tuning-decision.json") or
            decision["weights"] != weights() or decision["plan_sha256"] != sha256(ROOT / "plan.json") or
            decision["tuning_hashes"] != {m: sha256(ROOT / f"{m}-tuning.json") for m in (*RUNS, "bm25")}):
        raise ValueError("Dev gate missing or changed")
    evaluate_split("dev")


if __name__ == "__main__":
    main()
