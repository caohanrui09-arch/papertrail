"""Adapt an independent NLI classifier using only the project's training split."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import random
import re
import time

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from .data import write_json
from .retrieval import BM25, Corpus


LABEL_IDS = {"CONTRADICT": 0, "SUPPORT": 1, "INSUFFICIENT": 2}


def build_pairs(corpus: Corpus, claims: list[dict]) -> tuple[list[dict], dict]:
    """Positive rationales are gold; non-rationale/hard-negative NEI labels are weak."""
    lexical = BM25(corpus)
    pairs = {}
    too_long = 0

    def add(claim: dict, doc_id: str, sentence_ids: list[int], label: str, source: str) -> None:
        nonlocal too_long
        if not sentence_ids or len(sentence_ids) > 3:
            too_long += 1
            return
        premise = " ".join(corpus.by_id[doc_id]["sentences"][i] for i in sorted(sentence_ids))
        key = (premise, claim["claim"])
        record = {"premise": premise, "claim": claim["claim"], "label": LABEL_IDS[label],
                  "claim_id": claim["id"], "doc_id": doc_id, "sentence_ids": sorted(sentence_ids), "source": source}
        if key in pairs and pairs[key]["label"] != record["label"]:
            raise ValueError("Conflicting training text-pair labels")
        pairs[key] = record

    for claim in claims:
        words = set(re.findall(r"\w+", claim["claim"].casefold()))
        for doc_id, rationales in claim["evidence"].items():
            positive_ids = {i for rationale in rationales for i in rationale["sentences"]}
            for rationale in rationales:
                add(claim, doc_id, rationale["sentences"], rationale["label"], "gold_rationale")
            other = [i for i in range(len(corpus.by_id[doc_id]["sentences"])) if i not in positive_ids]
            other.sort(key=lambda i: -len(words & set(re.findall(r"\w+", corpus.by_id[doc_id]["sentences"][i].casefold()))))
            for i in other[:2]:
                add(claim, doc_id, [i], "INSUFFICIENT", "weak_non_rationale")
        negative_docs = [h["doc_id"] for h in lexical.search(claim["claim"], 5)
                         if h["doc_id"] not in claim["evidence"]]
        if negative_docs:
            doc_id = negative_docs[0]
            sentences = corpus.by_id[doc_id]["sentences"]
            ranked = sorted(range(len(sentences)),
                            key=lambda i: -len(words & set(re.findall(r"\w+", sentences[i].casefold()))))
            for i in ranked[:2]:
                add(claim, doc_id, [i], "INSUFFICIENT", "weak_unjudged_retrieval_negative")
        if not claim["evidence"]:
            for raw_doc in claim.get("cited_doc_ids", [])[:1]:
                doc_id = str(raw_doc)
                if doc_id in corpus.by_id and corpus.by_id[doc_id]["sentences"]:
                    add(claim, doc_id, [0], "INSUFFICIENT", "annotated_nei_document_first_sentence")
    lexical.db.close()
    rows = list(pairs.values())
    return rows, {"pairs": len(rows), "label_counts": dict(Counter(r["label"] for r in rows)),
                  "sources": dict(Counter(r["source"] for r in rows)), "rationales_over_three_skipped": too_long,
                  "claim_ids": sorted(c["id"] for c in claims),
                  "claim_split_sha256": hashlib.sha256(json.dumps(claims, sort_keys=True).encode()).hexdigest(),
                  "weak_negative_limitation": "Unannotated/non-rationale text may contain valid evidence; not verified neutral."}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("data/prepared"))
    parser.add_argument("--model", type=Path, default=Path(".cache/models/nli-MiniLM2-L6-H768"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=600)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.steps < 1 or args.batch < 1:
        parser.error("Positive steps/batch required")
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Refusing to overwrite verifier checkpoint")
    torch.set_num_threads(4)
    torch.manual_seed(args.seed)
    rng = random.Random(args.seed)
    corpus = Corpus(args.data / "documents.json")
    claims = json.loads((args.data / "train.json").read_text(encoding="utf-8"))
    pairs, audit = build_pairs(corpus, claims)
    buckets = defaultdict(list)
    for pair in pairs:
        buckets[pair["label"]].append(pair)
    if set(buckets) != {0, 1, 2}:
        raise ValueError("Training pairs lack an NLI class")
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(args.model, local_files_only=True)
    if [model.config.id2label[i].casefold() for i in range(3)] != ["contradiction", "entailment", "neutral"]:
        raise ValueError("Base NLI label IDs differ from training labels")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device).train()
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-5, weight_decay=0.01)
    start = time.perf_counter()
    losses = []
    exposures = Counter()
    for step in range(1, args.steps + 1):
        batch = []
        for _ in range(args.batch):
            label = rng.randrange(3)
            batch.append(rng.choice(buckets[label]))
            exposures[label] += 1
        inputs = tokenizer([p["premise"] for p in batch], [p["claim"] for p in batch], padding=True,
                           truncation="only_first", max_length=256, return_tensors="pt").to(device)
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast(device_type=device, dtype=torch.bfloat16,
                            enabled=device == "cuda" and torch.cuda.is_bf16_supported()):
            loss = model(**inputs, labels=torch.tensor([p["label"] for p in batch], device=device)).loss
        if not torch.isfinite(loss):
            raise ValueError("Non-finite verifier loss")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        losses.append(loss.item())
        if step == 1 or step % 100 == 0:
            print(json.dumps({"step": step, "loss": loss.item(), "seconds": time.perf_counter() - start}), flush=True)
    if device == "cuda":
        torch.cuda.synchronize()
    args.output.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(args.output, safe_serialization=True)
    tokenizer.save_pretrained(args.output)
    write_json(args.output / "run.json", {"corpus_fingerprint": corpus.fingerprint, "split": "train",
               "source": json.loads((args.model / "source.json").read_text()), "seed": args.seed,
               "steps": args.steps, "batch": args.batch, "lr": 2e-5, "max_length": 256,
               "label_ids": LABEL_IDS, "exposures": dict(exposures), "pairs_audit": audit,
               "losses": losses, "seconds": time.perf_counter() - start,
               "peak_allocated_mib": torch.cuda.max_memory_allocated() / 2**20 if device == "cuda" else None})
    print(json.dumps({"checkpoint": str(args.output), "pairs": audit["pairs"],
                      "label_counts": audit["label_counts"], "sources": audit["sources"]}, indent=2), flush=True)


if __name__ == "__main__":
    main()
