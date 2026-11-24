"""Sentence-level rationale selection, following SciFact's separate selector task."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import random
import time

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from .data import write_json
from .retrieval import Corpus
from .train_verifier import build_pairs


def rationale_pairs(corpus: Corpus, claims: list[dict]) -> tuple[list[dict], dict]:
    pairs = {}
    for claim in claims:
        for doc_id, rationales in claim["evidence"].items():
            positive = {i for r in rationales for i in r["sentences"]}
            for i, sentence in enumerate(corpus.by_id[doc_id]["sentences"]):
                key = (claim["claim"], sentence)
                label = int(i in positive)
                if key not in pairs or label:
                    pairs[key] = {"claim": claim["claim"], "sentence": sentence, "label": label,
                                  "claim_id": claim["id"], "source": "annotated_rationale_membership"}
    # Add exactly the same documented weak retrieval negatives used in the NLI adapter.
    nli_pairs, _ = build_pairs(corpus, claims)
    for row in nli_pairs:
        key = (row["claim"], row["premise"])
        if row["label"] == 2 and key not in pairs:
            pairs[key] = {"claim": row["claim"], "sentence": row["premise"], "label": 0,
                          "claim_id": row["claim_id"], "source": row["source"]}
    rows = list(pairs.values())
    return rows, {"pairs": len(rows), "label_counts": dict(Counter(r["label"] for r in rows)),
                  "sources": dict(Counter(r["source"] for r in rows)),
                  "claim_ids": sorted(c["id"] for c in claims),
                  "claim_split_sha256": hashlib.sha256(json.dumps(claims, sort_keys=True).encode()).hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("data/prepared"))
    parser.add_argument("--model", type=Path, default=Path(".cache/models/ms-marco-MiniLM-L6-v2"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.steps < 1:
        parser.error("Steps must be positive")
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Refusing to overwrite rationale checkpoint")
    torch.set_num_threads(4)
    torch.manual_seed(args.seed)
    rng = random.Random(args.seed)
    corpus = Corpus(args.data / "documents.json")
    claims = json.loads((args.data / "train.json").read_text(encoding="utf-8"))
    rows, audit = rationale_pairs(corpus, claims)
    buckets = defaultdict(list)
    for row in rows:
        buckets[row["label"]].append(row)
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(args.model, local_files_only=True)
    if model.config.num_labels != 1 or set(buckets) != {0, 1}:
        raise ValueError("Expected single-logit model and both rationale classes")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device).train()
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-5, weight_decay=0.01)
    start = time.perf_counter()
    losses = []
    for step in range(1, args.steps + 1):
        batch = [rng.choice(buckets[rng.randrange(2)]) for _ in range(16)]
        inputs = tokenizer([r["claim"] for r in batch], [r["sentence"] for r in batch], padding=True,
                           truncation=True, max_length=256, return_tensors="pt").to(device)
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast(device_type=device, dtype=torch.bfloat16,
                            enabled=device == "cuda" and torch.cuda.is_bf16_supported()):
            logits = model(**inputs).logits.flatten().float()
            labels = torch.tensor([r["label"] for r in batch], device=device, dtype=torch.float32)
            loss = torch.nn.functional.binary_cross_entropy_with_logits(logits, labels)
        if not torch.isfinite(loss):
            raise ValueError("Non-finite rationale loss")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        losses.append(loss.item())
        if step == 1 or step % 100 == 0:
            print(json.dumps({"step": step, "loss": loss.item(), "seconds": time.perf_counter() - start}), flush=True)
    args.output.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(args.output, safe_serialization=True)
    tokenizer.save_pretrained(args.output)
    write_json(args.output / "run.json", {"split": "train", "corpus_fingerprint": corpus.fingerprint,
               "source": json.loads((args.model / "source.json").read_text()), "seed": args.seed,
               "steps": args.steps, "batch": 16, "lr": 2e-5, "max_length": 256, "pairs_audit": audit,
               "seconds": time.perf_counter() - start, "losses": losses,
               "peak_allocated_mib": torch.cuda.max_memory_allocated() / 2**20 if device == "cuda" else None})
    print(json.dumps({"checkpoint": str(args.output), "pairs": len(rows), "label_counts": audit["label_counts"]}))


if __name__ == "__main__":
    main()
