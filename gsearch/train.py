"""Single-GPU T5 DSI adaptation: document indexing plus judged training queries."""
import argparse
import json
from pathlib import Path
import random
import time

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

from .data import write_json
from .retrieval import Corpus


def training_pairs(corpus: Corpus, claims: list[dict]) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    indexing = [("index: " + d["title"] + " " + " ".join(d["sentences"]), d["code"])
                for d in corpus.documents]
    queries = [("search: " + c["claim"], corpus.by_id[doc_id]["code"])
               for c in claims for doc_id in sorted(c["evidence"])]
    if not queries:
        raise ValueError("No judged training queries")
    return indexing, queries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("data/prepared"))
    parser.add_argument("--model", type=Path, default=Path(".cache/models/t5-small"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=800)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--max-input", type=int, default=160)
    parser.add_argument("--lr", type=float, default=5e-4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--query-fraction", type=float, default=0.5)
    args = parser.parse_args()
    if args.steps < 1 or args.batch < 1 or not 0 < args.query_fraction < 1:
        parser.error("Positive steps/batch and 0<query-fraction<1 required")
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Refusing to overwrite a run")
    rng = random.Random(args.seed)
    torch.manual_seed(args.seed)
    torch.set_num_threads(4)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
        torch.cuda.reset_peak_memory_stats()
    corpus = Corpus(args.data / "documents.json")
    claims = json.loads((args.data / "train.json").read_text(encoding="utf-8"))
    indexing, queries = training_pairs(corpus, claims)
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    model = AutoModelForSeq2SeqLM.from_pretrained(args.model, local_files_only=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(device).train()
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    args.output.mkdir(parents=True, exist_ok=True)
    exposures = {"index": 0, "query": 0}
    history = []
    start = time.perf_counter()
    mixed = device == "cuda" and torch.cuda.is_bf16_supported()
    for step in range(1, args.steps + 1):
        pairs = []
        for _ in range(args.batch):
            task = "query" if rng.random() < args.query_fraction else "index"
            pairs.append(rng.choice(queries if task == "query" else indexing))
            exposures[task] += 1
        inputs = tokenizer([p[0] for p in pairs], padding=True, truncation=True,
                           max_length=args.max_input, return_tensors="pt").to(device)
        labels = tokenizer(text_target=[p[1] for p in pairs], padding=True, return_tensors="pt")["input_ids"]
        labels[labels == tokenizer.pad_token_id] = -100
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast(device_type=device, dtype=torch.bfloat16, enabled=mixed):
            loss = model(**inputs, labels=labels.to(device)).loss
        if not torch.isfinite(loss):
            raise ValueError(f"Non-finite loss at step {step}")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        history.append({"step": step, "loss": loss.item()})
        if step == 1 or step % 50 == 0:
            print(json.dumps({"step": step, "loss": loss.item(),
                              "seconds": time.perf_counter() - start}), flush=True)
    if device == "cuda":
        torch.cuda.synchronize()
    elapsed = time.perf_counter() - start
    model.save_pretrained(args.output, safe_serialization=True)
    tokenizer.save_pretrained(args.output)
    source = json.loads((args.model / "source.json").read_text(encoding="utf-8"))
    run = {"model_source": source, "corpus_fingerprint": corpus.fingerprint,
           "steps": args.steps, "batch": args.batch, "max_input": args.max_input,
           "seed": args.seed, "lr": args.lr, "query_fraction": args.query_fraction,
           "exposures": exposures, "train_query_pairs": len(queries), "index_pairs": len(indexing),
           "seconds": elapsed, "device": device, "bf16_autocast": mixed,
           "gpu": torch.cuda.get_device_name() if device == "cuda" else None,
           "peak_allocated_mib": torch.cuda.max_memory_allocated() / 2**20 if device == "cuda" else None,
           "trainable_parameters": sum(p.numel() for p in model.parameters() if p.requires_grad),
           "selection": "fixed steps, no dev/test model selection", "losses": history}
    write_json(args.output / "run.json", run)
    print(json.dumps({k: v for k, v in run.items() if k not in {"model_source", "losses"}}, indent=2))


if __name__ == "__main__":
    main()
