"""Paired, budget-capped bundle evaluation with gold opened only after rollouts."""
import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import torch

from .budget_model import BudgetedToolModel
from .bundle_policies import run_policy
from .bundle_session import BundleBudget, BundleSession
from .data import write_json
from .retrieval import BM25, Corpus, GenerativeRetriever, Hybrid
from .verification import RerankedRetriever, load_verifier


POLICIES = ("single_pass", "rule_adaptive", "llm_agent")


def claim_score(prediction: dict | None, gold: dict) -> dict:
    evidence = gold["evidence"]
    labels = {r["label"] for groups in evidence.values() for r in groups}
    target = next(iter(labels)) if len(labels) == 1 else "INSUFFICIENT"
    records = prediction.get("evidence", []) if prediction else []
    correct = 0
    covered_labels = set()
    for row in records:
        if any(r["label"] == row["model_stance"] and set(r["sentences"]).issubset(row["sentence_ids"][:3])
               for r in evidence.get(row["doc_id"], [])):
            correct += 1
            covered_labels.add(row["model_stance"])
    verdict_ok = prediction is not None and prediction["verdict"] == target
    if evidence:
        success = verdict_ok and bool(correct) and (len(labels) == 1 or labels.issubset(covered_labels))
    else:
        success = verdict_ok and not records and not prediction.get("citations")
    return {"success": success, "verdict_correct": verdict_ok, "gold_verdict": target,
            "correct_documents": correct, "predicted_documents": len(records), "gold_documents": len(evidence),
            "gold_has_evidence": bool(evidence)}


def score_rollouts(rollouts: list[dict], gold: dict) -> dict:
    cases = []
    for report in rollouts:
        predictions = report["checked_results"] or {}
        per_claim = {key: claim_score(predictions.get(key), reference)
                     for key, reference in gold[report["task_id"]].items()}
        usage = report["tool_usage"]
        violations = [key for key in ("searches", "assessments", "document_claim_pairs")
                      if usage[key] > usage["ceilings"][key]]
        llm = report["llm_metadata"].get("llm_usage", {})
        for key in ("input_tokens", "output_tokens"):
            if llm.get(key, 0) > usage["ceilings"][key]:
                violations.append("llm_" + key)
        if llm.get("calls", 0) > usage["ceilings"]["max_steps"]:
            violations.append("llm_calls")
        cases.append({"task_id": report["task_id"], "completed_protocol": report["completed_protocol"],
                      "task_success": report["completed_protocol"] and not violations
                                      and all(row["success"] for row in per_claim.values()),
                      "claims": per_claim, "seconds": report["seconds"], "tool_usage": usage,
                      "classifier_work": report["classifier_work"], "llm_usage": llm,
                      "budget_violations": violations})
    atoms = [row for case in cases for row in case["claims"].values()]
    correct_docs = sum(row["correct_documents"] for row in atoms)
    predicted_docs = sum(row["predicted_documents"] for row in atoms)
    gold_docs = sum(row["gold_documents"] for row in atoms)
    precision = correct_docs / predicted_docs if predicted_docs else 0.0
    recall = correct_docs / gold_docs if gold_docs else 0.0
    return {"tasks": len(cases), "claim_verdict_distribution": dict(Counter(row["gold_verdict"] for row in atoms)),
            "completed_tasks": sum(case["completed_protocol"] for case in cases),
            "successful_tasks": sum(case["task_success"] for case in cases),
            "task_success_rate": sum(case["task_success"] for case in cases) / len(cases) if cases else 0,
            "claim_success_rate": sum(row["success"] for row in atoms) / len(atoms) if atoms else 0,
            "verdict_accuracy": sum(row["verdict_correct"] for row in atoms) / len(atoms) if atoms else 0,
            "document_evidence_precision": precision, "document_evidence_recall": recall,
            "document_evidence_f1": 2 * precision * recall / (precision + recall) if precision + recall else 0,
            "mean_seconds": sum(case["seconds"] for case in cases) / len(cases) if cases else 0,
            "total_searches": sum(case["tool_usage"]["searches"] for case in cases),
            "total_assessments": sum(case["tool_usage"]["assessments"] for case in cases),
            "total_document_claim_pairs": sum(case["tool_usage"]["document_claim_pairs"] for case in cases),
            "total_llm_input_tokens": sum(case["llm_usage"].get("input_tokens", 0) for case in cases),
            "total_llm_output_tokens": sum(case["llm_usage"].get("output_tokens", 0) for case in cases),
            "budget_violations": sum(bool(case["budget_violations"]) for case in cases), "cases": cases}


def code_hashes() -> dict:
    files = ["bundle_tasks.py", "bundle_session.py", "bundle_policies.py", "budget_model.py", "local_model.py",
             "benchmark_bundles.py", "verification.py", "evidence_models.py", "retrieval.py", "prompts/bundle.txt"]
    return {name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest() for name in files}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", type=Path, default=Path("data/stage3-bundles"))
    parser.add_argument("--data", type=Path, default=Path("data/prepared"))
    parser.add_argument("--split", choices=["tuning", "dev"], default="tuning")
    parser.add_argument("--limit", type=int, default=4)
    parser.add_argument("--policies", nargs="+", choices=POLICIES, default=list(POLICIES))
    parser.add_argument("--verifier-config", type=Path, default=Path("reports/stage2-locked-config.json"))
    parser.add_argument("--model", type=Path, default=Path(".cache/models/Qwen2.5-1.5B-Instruct"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.limit < 1 or len(args.policies) != len(set(args.policies)):
        parser.error("Positive limit and distinct policies required")
    task_file = args.tasks / f"{args.split}-public.json"
    audit = json.loads((args.tasks / "audit.json").read_text(encoding="utf-8"))
    public_hash = hashlib.sha256(task_file.read_bytes()).hexdigest()
    if public_hash != audit["splits"][args.split]["public_sha256"]:
        raise ValueError("Public task snapshot changed")
    tasks = json.loads(task_file.read_text(encoding="utf-8"))[:args.limit]
    budget = BundleBudget()
    manifest = {"split": args.split, "task_ids": [t["task_id"] for t in tasks], "policies": args.policies,
                "task_public_sha256": public_hash, "task_type": audit["task_type"], "ceilings": asdict(budget),
                "tasks_audit_sha256": hashlib.sha256((args.tasks / "audit.json").read_bytes()).hexdigest(),
                "verifier_config_sha256": hashlib.sha256(args.verifier_config.read_bytes()).hexdigest(),
                "model_source": json.loads((args.model / "source.json").read_text()), "code_hashes": code_hashes()}
    manifest_path = args.output / "manifest.json"
    if args.output.exists() and any(args.output.iterdir()):
        if not args.resume or not manifest_path.is_file() or json.loads(manifest_path.read_text()) != manifest:
            raise ValueError("Output exists; resume requires identical tasks, assets, code and budgets")
    else:
        args.output.mkdir(parents=True, exist_ok=True)
        write_json(manifest_path, manifest)
        write_json(args.output / "public_tasks.json", tasks)
    torch.set_num_threads(4)
    corpus = Corpus(args.data / "documents.json")
    verifier = load_verifier(corpus, args.verifier_config)
    lexical = BM25(corpus)
    generator = GenerativeRetriever(corpus, Path(verifier.config["retrieval_checkpoint"]))
    retrievers = {"bm25": lexical,
                  "hybrid_checked": RerankedRetriever(corpus, Hybrid(lexical, generator), verifier.relevance)}
    model = None
    if "llm_agent" in args.policies:
        model = BudgetedToolModel(model_id=str(args.model), device_map="cuda" if torch.cuda.is_available() else "cpu",
                                   torch_dtype="bfloat16" if torch.cuda.is_available() else "float32",
                                   model_kwargs={"local_files_only": True}, max_new_tokens=160, do_sample=False)
    # Common warm-up uses public tuning text only; every actual task/policy gets a fresh cache.
    warm = json.loads((args.tasks / "tuning-public.json").read_text(encoding="utf-8"))[0]["claims"]["A"]
    hits = retrievers["hybrid_checked"].search(warm, 2)
    verifier.assess(warm, [h["doc_id"] for h in hits])
    completed = []
    for task in tasks:
        for policy in args.policies:
            output = args.output / f"{task['task_id']}-{policy}.json"
            if args.resume and output.exists():
                report = json.loads(output.read_text(encoding="utf-8"))
            else:
                session = BundleSession(task["claims"], retrievers, verifier, budget)
                report = run_policy(policy, session, model)
                report["task_id"] = task["task_id"]
                write_json(output, report)
            completed.append(report)
            print(json.dumps({"task_id": task["task_id"], "policy": policy,
                              "completed": report["completed_protocol"], "seconds": report["seconds"],
                              "searches": report["tool_usage"]["searches"],
                              "pairs": report["tool_usage"]["document_claim_pairs"]}), flush=True)
    # Gold is opened only after ALL policies have finished; no rollout sees labels.
    gold_file = args.tasks / f"{args.split}-gold.json"
    if hashlib.sha256(gold_file.read_bytes()).hexdigest() != audit["splits"][args.split]["gold_sha256"]:
        raise ValueError("Scoring snapshot changed")
    gold = json.loads(gold_file.read_text(encoding="utf-8"))
    scores = {policy: score_rollouts([r for r in completed if r["policy"] == policy], gold) for policy in args.policies}
    write_json(args.output / "scores.json", {"split": args.split, "policies": scores,
               "scope": "small_controlled_composition_diagnostic_not_natural_multihop_benchmark"})
    print(json.dumps({policy: {k: v for k, v in score.items() if k != "cases"} for policy, score in scores.items()}, indent=2))


if __name__ == "__main__":
    main()
