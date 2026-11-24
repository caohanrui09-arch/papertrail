"""Frozen temporal MostPop/SAR recommendation benchmark with complete heldout positives."""
import argparse
import importlib.metadata as metadata
import json
from pathlib import Path
import time

import pandas as pd

from .data import write_json
from .evaluate import metrics
from .identifiers import sha256
from .paper_recommendation import load_recommender, upstream_sar


ROOT = Path("reports/stage9")
DATA = Path("data/stage9-recommendation")
METHODS = ("popular", "sar")


def read(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def state() -> dict:
    upstream_sar()
    return {"data": {name: sha256(DATA/name) for name in ("train.csv", "tuning.csv", "dev.csv", "catalog.json", "documents.json", "audit.json")},
        "code": {p: sha256(Path("gsearch")/p) for p in ("paper_recommendation.py", "prepare_recommendation.py", "discovery.py", "benchmark_recommendation.py", "retrieval.py", "evaluate.py")},
        "upstream_audit": sha256(ROOT / "upstream-audit.json"),
        "runtime": {n: metadata.version(n) for n in ("numpy", "pandas", "scipy", "smolagents")}}


def check_plan() -> dict:
    plan = read(ROOT / "plan.json")
    if plan["state"] != state():
        raise ValueError("Recommendation protocol drift")
    return plan


def evaluate_split(split: str) -> None:
    if any((ROOT / f"{m}-{split}.json").exists() for m in METHODS):
        raise ValueError("Refusing to overwrite recommendation output")
    started = time.perf_counter()
    engine = load_recommender()
    fit_seconds = time.perf_counter()-started
    frame = pd.read_csv(DATA / f"{split}.csv", dtype={"user_id": str, "arxiv_id": str})
    positives = frame[frame.rating == 1].groupby("user_id")["arxiv_id"].agg(set).to_dict()
    negatives = frame[frame.rating == -1].groupby("user_id")["arxiv_id"].agg(set).to_dict()
    for method in METHODS:
        rows = []
        for user in sorted(positives):
            started = time.perf_counter()
            hits = engine.recommend(user, 10, method)
            seconds = time.perf_counter()-started
            ids, relevant = [r["doc_id"] for r in hits], positives[user]
            if len(set(ids)) != len(ids) or set(ids)&engine.seen.get(user, set()):
                raise ValueError("Duplicate or historically rated recommendation")
            inside = relevant & set(engine.catalog)
            rows.append({"user_id": user, "relevant": sorted(relevant), "recommendations": hits,
                **metrics(ids, relevant, 10), "seconds": seconds,
                "warm": user in engine.model.user2index,
                "catalog_recall": len(set(ids)&inside)/len(inside) if inside else None,
                "catalog_positive_count": len(inside),
                "observed_future_dislikes_returned": len(set(ids)&negatives.get(user, set()))})
        summary = {k+"@10": sum(r[k] for r in rows)/len(rows) for k in ("recall", "hit", "mrr", "ndcg")}
        summary.update({"evaluated_users_with_future_likes": len(rows), "catalog_items": len(engine.catalog),
            "warm_users": sum(r["warm"] for r in rows), "cold_users": sum(not r["warm"] for r in rows),
            "mean_seconds": sum(r["seconds"] for r in rows)/len(rows),
            "catalog_coverage": len({h["doc_id"] for r in rows for h in r["recommendations"]})/len(engine.catalog),
            "future_positive_catalog_coverage": sum(r["catalog_positive_count"] for r in rows)/sum(len(r["relevant"]) for r in rows),
            "observed_future_dislikes_returned": sum(r["observed_future_dislikes_returned"] for r in rows)})
        groups = {}
        for warm in (True, False):
            group = [r for r in rows if r["warm"] == warm]
            groups["warm" if warm else "cold"] = {"users": len(group), **{
                k: sum(r[k] for r in group)/len(group) if group else None for k in ("recall", "ndcg")}}
        # Row-level ratings and predictions are local-only derived data under the source license.
        destination = DATA / f"{method}-{split}-predictions.json"
        write_json(destination, {"method": method, "split": split, "users": rows})
        record = {"method": method, "split": split, "k": 10, "summary": summary, "groups": groups,
                  "fit_seconds_including_load": fit_seconds, "plan_sha256": sha256(ROOT / "plan.json"),
                  "predictions_sha256": sha256(destination), "row_level_output": "kept locally in ignored data/",
                  "denominator": "all future explicit likes, including outside trained catalog; no sampled negatives",
                  "scope": "logged rating completion under global time holdout; not unbiased CTR or online recommendation"}
        write_json(ROOT / f"{method}-{split}.json", record)
        print(json.dumps(record), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("plan", "tuning", "lock", "dev"), required=True)
    args = parser.parse_args()
    if args.phase == "plan":
        if (ROOT / "plan.json").exists():
            raise ValueError("Refusing to overwrite pre-evaluation protocol")
        write_json(ROOT / "plan.json", {"frozen_before_evaluation": True, "state": state(), "methods": METHODS,
            "k": 10, "selection": "tuning NDCG, Recall, MRR; exact ties prefer popular",
            "training": "only pre-cutoff positive ratings, binary affinity, SAR Jaccard threshold1; no time-decay or tuning grid",
            "filter": "all train-period ratings, positive and negative; cold-user popularity fallback",
            "evaluation": "all heldout users with explicit likes; all their likes in denominator; report warm/cold and catalog limitations",
            "integration": "recommend_papers, personalized search_papers, read_paper; same arxiv namespace; no legacy T5/NLI transfer"})
        return
    check_plan()
    if args.phase == "lock":
        if (ROOT / "locked-before-dev.json").exists():
            raise ValueError("Refusing to overwrite selection")
        results = {m: read(ROOT / f"{m}-tuning.json") for m in METHODS}
        selected = max(METHODS, key=lambda m: (results[m]["summary"]["ndcg@10"], results[m]["summary"]["recall@10"],
                                               results[m]["summary"]["mrr@10"], m == "popular"))
        write_json(ROOT / "locked-before-dev.json", {"selected": selected, "plan_sha256": sha256(ROOT / "plan.json"),
            "tuning": {m: sha256(ROOT / f"{m}-tuning.json") for m in METHODS}, "frozen_before_dev": True})
        print(json.dumps({"selected": selected}), flush=True)
        return
    if args.phase == "dev":
        lock = read(ROOT / "locked-before-dev.json")
        if (lock["plan_sha256"] != sha256(ROOT / "plan.json") or
                lock["tuning"] != {m: sha256(ROOT / f"{m}-tuning.json") for m in METHODS}):
            raise ValueError("Frozen selection changed")
    evaluate_split(args.phase)


if __name__ == "__main__":
    main()
