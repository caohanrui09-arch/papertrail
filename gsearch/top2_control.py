"""Post-hoc explanatory control inferred from the observed LLM schedule, not preregistered."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import torch

from .benchmark_bundles import score_rollouts
from .bundle_policies import classifier_work
from .bundle_session import BundleBudget, BundleSession
from .data import write_json
from .retrieval import BM25, Corpus, GenerativeRetriever, Hybrid
from .verification import RerankedRetriever, load_verifier


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, default=Path("reports/stage3-dev"))
    parser.add_argument("--data", type=Path, default=Path("data/prepared"))
    parser.add_argument("--tasks", type=Path, default=Path("data/stage3-bundles"))
    parser.add_argument("--verifier-config", type=Path, default=Path("reports/stage2-locked-config.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/stage3-posthoc-top2"))
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Refusing to overwrite post-hoc control")
    tasks = json.loads((args.reference / "public_tasks.json").read_text(encoding="utf-8"))
    manifest = json.loads((args.reference / "manifest.json").read_text(encoding="utf-8"))
    audit_path = args.tasks / "audit.json"
    if hashlib.sha256(audit_path.read_bytes()).hexdigest() != manifest["tasks_audit_sha256"]:
        raise ValueError("Task provenance changed")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    public = json.loads((args.tasks / f"{manifest['split']}-public.json").read_text(encoding="utf-8"))
    selected = {task["task_id"]: task for task in public}
    if tasks != [selected[key] for key in manifest["task_ids"]]:
        raise ValueError("Control task inputs differ from the original selection")
    if hashlib.sha256(args.verifier_config.read_bytes()).hexdigest() != manifest["verifier_config_sha256"]:
        raise ValueError("Control must use the original verifier configuration")
    budget = BundleBudget(**manifest["ceilings"])
    torch.set_num_threads(4)
    corpus = Corpus(args.data / "documents.json")
    verifier = load_verifier(corpus, args.verifier_config)
    lexical = BM25(corpus)
    generator = GenerativeRetriever(corpus, Path(verifier.config["retrieval_checkpoint"]))
    retrievers = {"bm25": lexical,
                  "hybrid_checked": RerankedRetriever(corpus, Hybrid(lexical, generator), verifier.relevance)}
    warm = json.loads((args.tasks / "tuning-public.json").read_text(encoding="utf-8"))[0]["claims"]["A"]
    hits = retrievers["hybrid_checked"].search(warm, 2)
    verifier.assess(warm, [hit["doc_id"] for hit in hits])
    args.output.mkdir(parents=True, exist_ok=True)
    write_json(args.output / "manifest.json", {"scope": "posthoc_explanatory_control_not_preregistered",
               "reason": "Agent always used original-query Top2 for A and B and never retried",
               "reference_manifest_sha256": hashlib.sha256((args.reference / "manifest.json").read_bytes()).hexdigest(),
               "task_ids": [task["task_id"] for task in tasks], "ceilings": manifest["ceilings"]})
    results = []
    for task in tasks:
        verifier.cache.clear()
        before = classifier_work(verifier)
        start = time.perf_counter()
        session = BundleSession(task["claims"], retrievers, verifier, budget)
        for key in task["claims"]:
            hits = session.search(key, "", "hybrid_checked", 2).get("hits", [])
            if hits:
                session.assess(key, [hit["doc_id"] for hit in hits])
        checked = session.finalize(session.expected_answer())
        after = classifier_work(verifier)
        report = {"task_id": task["task_id"], "policy": "posthoc_top2", "completed_protocol": True,
                  "checked_results": checked, "diagnostic_progress": session.progress(),
                  "seconds": time.perf_counter() - start, "tool_usage": session.usage(),
                  "classifier_work": {name: {k: v - before[name][k] for k, v in values.items()}
                                      for name, values in after.items()}, "tool_trace": session.trace,
                  "error": None, "llm_metadata": {}, "scope": "posthoc_explanatory_control_not_preregistered"}
        write_json(args.output / f"{task['task_id']}.json", report)
        results.append(report)
    # Labels still enter only the evaluation stage, after every control rollout.
    gold_path = args.tasks / f"{manifest['split']}-gold.json"
    if hashlib.sha256(gold_path.read_bytes()).hexdigest() != audit["splits"][manifest["split"]]["gold_sha256"]:
        raise ValueError("Control scoring data changed")
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    score = score_rollouts(results, gold)
    score["scope"] = "posthoc_explanatory_control_not_preregistered"
    write_json(args.output / "scores.json", score)
    print(json.dumps({k: v for k, v in score.items() if k != "cases"}, indent=2))


if __name__ == "__main__":
    main()
