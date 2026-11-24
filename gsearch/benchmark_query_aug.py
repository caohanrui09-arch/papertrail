"""Pre-training and pre-dev locks for matched query-augmentation continuations."""
import argparse
import gc
import json
from pathlib import Path

import torch

from .data import write_json
from .evaluate import evaluate
from .identifiers import sha256
from .retrieval import BM25, Corpus, GenerativeRetriever, Hybrid
from .train_query_aug import DATA, INITIAL, QUERIES, TRAINING, checkpoint_hashes, input_state


RUNS = {"control": Path("runs/t5-title-control-plus4000-seed42"),
        "qg": Path("runs/t5-title-qg-plus4000-seed42")}
METHODS = ("bm25", "title4000", "control8000", "qg8000", "qg_rrf")


def read(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def code_hashes() -> dict[str, str]:
    return {name: sha256(Path("gsearch") / name) for name in (
        "query_augmentation.py", "train_query_aug.py", "benchmark_query_aug.py",
        "retrieval.py", "evaluate.py", "train.py", "data.py", "identifiers.py")}


def current_state() -> dict:
    return {"inputs": input_state(), "code_hashes": code_hashes(),
            "evaluation_claims": {split: sha256(DATA / f"{split}.json") for split in ("tuning", "dev")}}


def check_state(plan: dict) -> None:
    for key, value in current_state().items():
        if plan[key] != value:
            raise ValueError(f"Pre-training protocol drift: {key}")


def trained_models(plan: dict) -> dict:
    runs = {mode: read(folder / "run.json") for mode, folder in RUNS.items()}
    for mode, run in runs.items():
        if any(run[key] != value for key, value in TRAINING.items()) or run["mode"] != mode:
            raise ValueError("Wrong continuation schedule")
        if run["inputs"] != plan["inputs"] or run["code_hashes"] != plan["code_hashes"]:
            raise ValueError("Continuation used different inputs or code")
    a, b = runs["control"], runs["qg"]
    if a["schedule_sha256"] != b["schedule_sha256"] or a["per_document_visits"] != b["per_document_visits"]:
        raise ValueError("Continuation sampling was not paired")
    if a["usage"]["label_tokens"] != b["usage"]["label_tokens"] or a["exposures"]["gold_query"] != b["exposures"]["gold_query"]:
        raise ValueError("Unequal labels or gold-query budget")
    return {mode: checkpoint_hashes(folder) for mode, folder in RUNS.items()}


def run_evaluation(split: str, output: Path) -> None:
    if any((output / f"{name}-{split}.json").exists() for name in METHODS):
        raise ValueError("Refusing to overwrite evaluation")
    corpus = Corpus(DATA / "documents.json")
    claims = read(DATA / f"{split}.json")
    lexical = BM25(corpus)
    def save(searcher: object, name: str) -> None:
        print(json.dumps({"split": split, "method": name, "status": "started"}), flush=True)
        report = evaluate(searcher, claims, 10)
        report.update({"method": name, "split": split, "corpus_fingerprint": corpus.fingerprint,
                       "beam": 10, "k": 10, "plan_sha256": sha256(output / "plan.json"),
                       "protocol": "fixed methods, matched continuation schedules; reused public dev"})
        write_json(output / f"{name}-{split}.json", report)
        print(json.dumps({"method": name, "summary": report["summary"]}), flush=True)
    save(lexical, "bm25")
    for name, folder in (("title4000", INITIAL), ("control8000", RUNS["control"]), ("qg8000", RUNS["qg"])):
        neural = GenerativeRetriever(corpus, folder, 10)
        save(neural, name)
        if name == "qg8000":
            save(Hybrid(lexical, neural), "qg_rrf")
        del neural
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    lexical.db.close()


def overlap_audit() -> dict:
    """Diagnostic only, after models freeze: do not filter any training query."""
    from .query_augmentation import normalize
    records = read(QUERIES / "queries.json")
    sources = {}
    for r in records:
        for q in r["queries"]:
            sources.setdefault(normalize(q), []).append(r["doc_id"])
    result = {}
    for split in ("train", "tuning", "dev"):
        rows = read(DATA / f"{split}.json")
        matches = [{"claim_id": c["id"], "claim": c["claim"], "source_doc_ids": sources[normalize(c["claim"]) ]}
                   for c in rows if normalize(c["claim"]) in sources]
        result[split] = {"exact_normalized_matches": len(matches), "matches": matches}
    return {"performed_after_model_freeze": True, "used_for_filtering_or_selection": False,
            "normalization": "collapse whitespace and casefold; no semantic near-duplicate claim", "splits": result}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("plan", "tuning", "lock", "dev"), required=True)
    parser.add_argument("--output", type=Path, default=Path("reports/stage5"))
    args = parser.parse_args()
    torch.set_num_threads(4)
    plan_path = args.output / "plan.json"
    if args.phase == "plan":
        if plan_path.exists() or any(folder.exists() for folder in RUNS.values()):
            raise ValueError("Plan must precede both continuations")
        audit = read(QUERIES / "audit.json")
        if audit["queries_sha256"] != sha256(QUERIES / "queries.json") or audit["documents"] != 5183:
            raise ValueError("Incomplete or changed generation")
        from .query_augmentation import teacher_state
        generation = read(QUERIES / "manifest.json")
        if (audit["manifest_sha256"] != sha256(QUERIES / "manifest.json") or
                generation["teacher"] != teacher_state() or
                generation["code_sha256"] != sha256(Path("gsearch/query_augmentation.py")) or
                generation["documents_sha256"] != sha256(DATA / "documents.json")):
            raise ValueError("Generation provenance differs from actual inputs")
        write_json(plan_path, {**current_state(), "training": TRAINING, "methods": METHODS,
                   "locked_before_continuation": True, "beam": 10, "k": 10,
                   "comparison": "control vs qg both initialize same stage4 model, fresh optimizer",
                   "rrf": "equal weights, constant60, top10 per branch, predetermined",
                   "selection": "fixed4000 continuation per branch, no tuning selection",
                   "dev_caveat": "public dev reused, descriptive single-seed comparison"})
        print("Both continuation protocols frozen before training", flush=True)
        return
    plan = read(plan_path)
    check_state(plan)
    weights = trained_models(plan)
    if args.phase == "lock":
        locked = args.output / "locked-before-dev.json"
        if locked.exists():
            raise ValueError("Refusing to overwrite dev lock")
        write_json(locked, {"locked_before_dev": True, "models": weights,
                   "plan_sha256": sha256(plan_path),
                   "tuning": {m: sha256(args.output / f"{m}-tuning.json") for m in METHODS}})
        write_json(args.output / "overlap-audit.json", overlap_audit())
        print("Models/config/tokenizers frozen; overlap audit performed without filtering", flush=True)
        return
    if args.phase == "dev":
        lock = read(args.output / "locked-before-dev.json")
        if lock["models"] != weights or lock["plan_sha256"] != sha256(plan_path):
            raise ValueError("Models or protocol changed after dev lock")
        if lock["tuning"] != {m: sha256(args.output / f"{m}-tuning.json") for m in METHODS}:
            raise ValueError("Tuning outputs changed after lock")
    run_evaluation(args.phase, args.output)


if __name__ == "__main__":
    main()
