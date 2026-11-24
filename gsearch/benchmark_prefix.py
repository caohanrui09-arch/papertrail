"""Fixed-model 2x2 prefix-index/beam-width evaluation using upstream ZeroGR tree."""
import argparse
import importlib.metadata as metadata
import json
from pathlib import Path

import torch

from .data import write_json
from .evaluate import evaluate
from .identifiers import sha256
from .prefix_decoder import PrefixIndex, PrefixRetriever, VENDOR, upstream_tree_class
from .retrieval import BM25, Corpus, GenerativeRetriever
from .train_query_aug import checkpoint_hashes


ROOT = Path("reports/stage7")
DATA = Path("data/stage4-title")
MODEL = Path("runs/t5-title12-4000-seed42")
METHODS = ("full_b10", "full_b50", "short_b10", "short_b50")


def read(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def current_state() -> dict:
    upstream_tree_class()
    return {"code_hashes": {p: sha256(Path("gsearch") / p) for p in (
                "prefix_decoder.py", "benchmark_prefix.py", "retrieval.py", "evaluate.py")},
            "vendor_hashes": {p.name: sha256(p) for p in VENDOR.iterdir() if p.is_file()},
            "upstream_audit_sha256": sha256(ROOT / "upstream-audit.json"),
            "model_assets": checkpoint_hashes(MODEL),
            "data_files": {p.name: sha256(p) for p in DATA.glob("*.json")},
            "old_tuning_reference_sha256": sha256(Path("reports/stage4/title-tuning.json")),
            "runtime": {n: metadata.version(n) for n in ("torch", "numpy", "transformers", "accelerate", "sentencepiece")}}


def check_state(plan: dict) -> None:
    if plan["state"] != current_state():
        raise ValueError("Prefix experiment drift: code, tree, model, data or runtime changed")


def run_evaluation(split: str) -> None:
    if any((ROOT / f"{m}-{split}.json").exists() for m in (*METHODS, "bm25")):
        raise ValueError("Refusing to overwrite evaluation")
    corpus = Corpus(DATA / "documents.json")
    claims = read(DATA / f"{split}.json")
    lexical = BM25(corpus)
    baseline = evaluate(lexical, claims, 10)
    baseline.update({"method": "bm25", "split": split, "role": "strong reference, excluded from T5 selection"})
    write_json(ROOT / f"bm25-{split}.json", baseline)
    lexical.db.close()
    neural = GenerativeRetriever(corpus, MODEL, 10)
    indexes = {"full": PrefixIndex(corpus, neural.tokenizer, False),
               "short": PrefixIndex(corpus, neural.tokenizer, True)}
    for label, index in indexes.items():
        destination = ROOT / f"{label}-index.json"
        record = {"stats": index.stats, "aliases": index.aliases}
        if destination.exists() and read(destination) != record:
            raise ValueError("Alias index changed across tuning/dev")
        if not destination.exists():
            write_json(destination, record)
    for method in METHODS:
        label, width = method.split("_b")
        retriever = PrefixRetriever(neural, indexes[label], int(width))
        print(json.dumps({"split": split, "method": method, "status": "started"}), flush=True)
        result = evaluate(retriever, claims, 10)
        profile = retriever.receipts[1:]  # evaluate's first search is excluded warmup.
        if len(profile) != len(result["queries"]):
            raise ValueError("Decode work records are incomplete")
        result.update({"method": method, "split": split, "beam": int(width), "tree": indexes[label].stats,
                       "decode_work": profile, "plan_sha256": sha256(ROOT / "plan.json"),
                       "work_note": "beam_decoder_slots=beam*generation steps, a work proxy not FLOPs"})
        write_json(ROOT / f"{method}-{split}.json", result)
        print(json.dumps({"method": method, "summary": result["summary"], "tree": result["tree"]}), flush=True)


def legacy_equivalence() -> None:
    current = read(ROOT / "full_b10-tuning.json")["queries"]
    previous = read(Path("reports/stage4/title-tuning.json"))["queries"]
    if len(current) != len(previous):
        raise ValueError("Full-tree baseline query count differs")
    for a, b in zip(current, previous):
        if (a["claim_id"] != b["claim_id"] or [h["doc_id"] for h in a["predictions"]] !=
                [h["doc_id"] for h in b["predictions"]]):
            raise ValueError("Full-tree adapter does not reproduce original complete ranking")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("plan", "tuning", "lock", "dev"), required=True)
    args = parser.parse_args()
    torch.set_num_threads(4)
    path = ROOT / "plan.json"
    if args.phase == "plan":
        if path.exists() or any((ROOT / f"{m}-tuning.json").exists() for m in METHODS):
            raise ValueError("Plan must precede tuning")
        write_json(path, {"locked_before_tuning": True, "state": current_state(), "methods": METHODS,
                         "k": 10, "beams": [10, 50], "new_training_steps": 0,
                         "selection": "tuning NDCG, MRR, Recall, then smaller beam and full index",
                         "decode": "HF native beam search, do_sample=False, length_penalty1, no score renormalization",
                         "scope": "short token-prefix aliases change EOS position and score length; not a full ZeroGR reproduction",
                         "dev_caveat": "reused public dev; descriptive single-model comparison"})
        print("2x2 prefix/beam design frozen before tuning", flush=True)
        return
    plan = read(path)
    check_state(plan)
    if args.phase == "lock":
        target = ROOT / "locked-before-dev.json"
        if target.exists() or any((ROOT / f"{m}-dev.json").exists() for m in METHODS):
            raise ValueError("Dev lock must precede all dev outputs")
        legacy_equivalence()
        variants = [read(ROOT / f"{m}-tuning.json") for m in METHODS]
        selected = max(variants, key=lambda r: (r["summary"]["ndcg@10"], r["summary"]["mrr@10"],
                    r["summary"]["recall@10"], -r["beam"], not r["tree"]["compressed"]))["method"]
        write_json(target, {"locked_before_dev": True, "selected": selected,
                   "plan_sha256": sha256(path), "legacy_rankings_match": True,
                   "tuning": {m: sha256(ROOT / f"{m}-tuning.json") for m in (*METHODS, "bm25")},
                   "indexes": {n: sha256(ROOT / f"{n}-index.json") for n in ("full", "short")}})
        print(json.dumps({"selected_on_tuning": selected, "legacy_equivalence": True}), flush=True)
        return
    if args.phase == "dev":
        lock = read(ROOT / "locked-before-dev.json")
        if (lock["plan_sha256"] != sha256(path) or
                lock["tuning"] != {m: sha256(ROOT / f"{m}-tuning.json") for m in (*METHODS, "bm25")} or
                lock["indexes"] != {n: sha256(ROOT / f"{n}-index.json") for n in ("full", "short")}):
            raise ValueError("Frozen selection or indexes changed")
    run_evaluation(args.phase)


if __name__ == "__main__":
    main()
