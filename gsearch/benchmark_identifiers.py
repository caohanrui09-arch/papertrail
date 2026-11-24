"""Freeze a textual-identifier experiment, then evaluate all predefined methods."""
import argparse
import gc
import json
from pathlib import Path

import torch

from .data import write_json
from .evaluate import evaluate
from .identifiers import sha256
from .retrieval import BM25, Corpus, GenerativeRetriever, Hybrid


SOURCE = Path("data/prepared")
VARIANT = Path("data/stage4-title")
BASE = Path(".cache/models/t5-small")
NUMERIC = Path("runs/t5-dsi-4000-seed42")
TITLE = Path("runs/t5-title12-4000-seed42")
CONFIG = {"steps": 4000, "batch": 8, "max_input": 160, "lr": 0.0005,
          "seed": 42, "query_fraction": 0.5}
METHODS = ("bm25", "numeric", "title", "title_rrf")


def read(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def code_hashes() -> dict[str, str]:
    return {name: sha256(Path("gsearch") / name) for name in (
        "identifiers.py", "benchmark_identifiers.py", "train.py", "retrieval.py", "evaluate.py", "data.py")}


def state() -> dict:
    return {"code_hashes": code_hashes(),
            "source_files": {p.name: sha256(p) for p in SOURCE.glob("*.json")},
            "variant_files": {p.name: sha256(p) for p in VARIANT.glob("*.json")},
            "base_weights_sha256": sha256(BASE / "model.safetensors"),
            "base_source_sha256": sha256(BASE / "source.json"),
            "numeric_weights_sha256": sha256(NUMERIC / "model.safetensors"),
            "numeric_run_sha256": sha256(NUMERIC / "run.json"),
            "tokenizer_config_files": {f"{folder}/{p.name}": sha256(p) for folder in (BASE, NUMERIC)
                                       for p in folder.iterdir() if p.suffix in (".json", ".model")}}


def assert_same(actual: dict, expected: dict) -> None:
    if actual != expected:
        raise ValueError("Frozen experiment drift detected")


def training_state() -> dict:
    run = read(TITLE / "run.json")
    old = read(NUMERIC / "run.json")
    for key, value in CONFIG.items():
        if run[key] != value or old[key] != value:
            raise ValueError(f"Training budget differs: {key}")
    audit = read(VARIANT / "identifier-audit.json")
    if run["corpus_fingerprint"] != audit["title_fingerprint"]:
        raise ValueError("Title checkpoint belongs to a different catalog")
    for name, metadata in (("numeric", old), ("title", run)):
        receipt = audit["training_receipts"][name]
        if metadata["exposures"] != receipt["exposures"] or metadata["train_query_pairs"] != receipt["train_query_pairs"]:
            raise ValueError("Trainer sampling differs from receipt")
    assert_same(run["model_source"], old["model_source"])
    return {"title_weights_sha256": sha256(TITLE / "model.safetensors"),
            "title_run_sha256": sha256(TITLE / "run.json")}


def run_evaluation(split: str, output: Path) -> None:
    if any((output / f"{name}-{split}.json").exists() for name in METHODS):
        raise ValueError("Refusing to overwrite evaluation; preserve partial results")
    original = Corpus(SOURCE / "documents.json")
    variant = Corpus(VARIANT / "documents.json")
    claims = read(SOURCE / f"{split}.json")
    # Assert only codes changed, all original IDs/content and all claim bytes are identical.
    for a, b in zip(original.documents, variant.documents):
        assert_same({k: v for k, v in a.items() if k != "code"},
                    {k: v for k, v in b.items() if k != "code"})
    if len(original.documents) != len(variant.documents) or sha256(SOURCE / f"{split}.json") != sha256(VARIANT / f"{split}.json"):
        raise ValueError("Unequal source data")
    lexical = BM25(original)
    metadata = {"split": split, "beam": 10, "k": 10, "source_corpus": original.fingerprint,
                "claim_ids_sha256": sha256(SOURCE / f"{split}.json"),
                "plan_sha256": sha256(output / "plan.json"),
                "protocol": "fixed architecture/steps, no tuning-based selection; reused public dev"}
    def save(searcher: object, name: str) -> None:
        print(json.dumps({"split": split, "method": name, "status": "started"}), flush=True)
        result = evaluate(searcher, claims, 10)
        result.update(metadata)
        result["method"] = name
        write_json(output / f"{name}-{split}.json", result)
        print(json.dumps({"split": split, "method": name, "summary": result["summary"]}), flush=True)
    save(lexical, "bm25")
    numeric = GenerativeRetriever(original, NUMERIC, 10)
    save(numeric, "numeric")
    del numeric
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    title = GenerativeRetriever(variant, TITLE, 10)
    save(title, "title")
    save(Hybrid(lexical, title), "title_rrf")
    lexical.db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("plan", "tuning", "lock", "dev"), required=True)
    parser.add_argument("--output", type=Path, default=Path("reports/stage4"))
    args = parser.parse_args()
    torch.set_num_threads(4)
    plan_path = args.output / "plan.json"
    if args.phase == "plan":
        if plan_path.exists() or TITLE.exists():
            raise ValueError("Plan must precede title training; refusing overwrite")
        audit = read(VARIANT / "identifier-audit.json")
        write_json(plan_path, {"locked_before_title_training": True, "state": state(),
                   "training": CONFIG, "prefix_tokens": audit["prefix_tokens"],
                   "beam": 10, "k": 10, "methods": METHODS,
                   "rrf": "equal weights, rank constant60, top10 per branch",
                   "selection": "no hyperparameter/seed/checkpoint selection by tuning or dev",
                   "dev_caveat": "public dev reused in preceding stages; descriptive comparison"})
        print("Pre-training protocol saved", flush=True)
        return
    plan = read(plan_path)
    assert_same(state(), plan["state"])
    weights = training_state()
    if args.phase == "lock":
        lock_path = args.output / "locked-before-dev.json"
        if lock_path.exists():
            raise ValueError("Refusing to overwrite dev lock")
        tuning = {name: sha256(args.output / f"{name}-tuning.json") for name in METHODS}
        write_json(lock_path, {"locked_before_dev": True, "state": plan["state"],
                              "weights": weights, "plan_sha256": sha256(plan_path), "tuning": tuning})
        print("Weights and all four tuning outputs frozen before dev", flush=True)
        return
    if args.phase == "dev":
        lock = read(args.output / "locked-before-dev.json")
        assert_same(weights, lock["weights"])
        assert_same(plan["state"], lock["state"])
        assert_same({name: sha256(args.output / f"{name}-tuning.json") for name in METHODS}, lock["tuning"])
        if sha256(plan_path) != lock["plan_sha256"]:
            raise ValueError("Plan changed after locking")
    run_evaluation(args.phase, args.output)


if __name__ == "__main__":
    main()
