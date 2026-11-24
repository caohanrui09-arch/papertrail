"""Paired continuation: corpus indexing versus generated search queries."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import time

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

from .data import write_json
from .identifiers import sha256
from .retrieval import Corpus
from .train import training_pairs


INITIAL = Path("runs/t5-title12-4000-seed42")
DATA = Path("data/stage4-title")
QUERIES = Path("data/stage5-queries")
TRAINING = {"steps": 4000, "batch": 8, "max_input": 160, "lr": 0.0005,
            "seed": 42, "query_fraction": 0.5}


def checkpoint_hashes(path: Path) -> dict[str, str]:
    return {p.name: sha256(p) for p in path.iterdir()
            if p.name == "model.safetensors" or p.suffix in (".json", ".model")}


class PairedSampler:
    def __init__(self, corpus: Corpus, claims: list[dict], records: list[dict], mode: str,
                 seed: int = 42, query_fraction: float = 0.5):
        if mode not in ("control", "qg") or not 0 < query_fraction < 1:
            raise ValueError("Invalid continuation sampler")
        self.corpus, self.mode = corpus, mode
        self.indexing, self.gold = training_pairs(corpus, claims)
        self.records = {r["doc_id"]: r for r in records}
        if len(self.records) != len(records) or set(self.records) != set(corpus.by_id):
            raise ValueError("Synthetic queries must cover each document exactly once")
        if any(not r["queries"] or any(not isinstance(q, str) or not q.strip() for q in r["queries"])
               for r in records):
            raise ValueError("Synthetic query lists must be nonempty text")
        self.rng = random.Random(seed)
        self.query_fraction = query_fraction
        self.visits = {d: 0 for d in corpus.by_id}
        self.counts = {"gold_query": 0, "index": 0, "synthetic_query": 0}
        self.schedule = hashlib.sha256()

    def sample(self, size: int) -> list[tuple[str, str]]:
        if type(size) is not int or size < 1:
            raise ValueError("Positive batch size required")
        pairs = []
        for _ in range(size):
            role = "query" if self.rng.random() < self.query_fraction else "index"
            position = self.rng.randrange(len(self.gold) if role == "query" else len(self.indexing))
            self.schedule.update(f"{role}:{position}\n".encode())
            if role == "query":
                pair = self.gold[position]
                self.counts["gold_query"] += 1
            else:
                doc = self.corpus.documents[position]
                if self.mode == "control":
                    pair = self.indexing[position]
                    self.counts["index"] += 1
                else:
                    options = self.records[doc["doc_id"]]["queries"]
                    query = options[self.visits[doc["doc_id"]] % len(options)]
                    pair = ("search: " + query, doc["code"])
                    self.counts["synthetic_query"] += 1
                self.visits[doc["doc_id"]] += 1
            pairs.append(pair)
        return pairs


def input_state() -> dict:
    return {"initial": checkpoint_hashes(INITIAL),
            "documents_sha256": sha256(DATA / "documents.json"),
            "train_sha256": sha256(DATA / "train.json"),
            "queries_sha256": sha256(QUERIES / "queries.json"),
            "generation_audit_sha256": sha256(QUERIES / "audit.json")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("control", "qg"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Refusing to overwrite continuation")
    protocol = json.loads(Path("reports/stage5/plan.json").read_text(encoding="utf-8"))
    # Lazy import avoids a module cycle and covers trainer + evaluator source drift.
    from .benchmark_query_aug import code_hashes
    if protocol["inputs"] != input_state() or protocol["code_hashes"] != code_hashes() or protocol["training"] != TRAINING:
        raise ValueError("Continuation differs from pre-training protocol")
    torch.manual_seed(TRAINING["seed"])
    torch.set_num_threads(4)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda":
        torch.cuda.manual_seed_all(TRAINING["seed"])
        torch.cuda.reset_peak_memory_stats()
    corpus = Corpus(DATA / "documents.json")
    claims = json.loads((DATA / "train.json").read_text(encoding="utf-8"))
    records = json.loads((QUERIES / "queries.json").read_text(encoding="utf-8"))
    sampler = PairedSampler(corpus, claims, records, args.mode,
                            TRAINING["seed"], TRAINING["query_fraction"])
    tokenizer = AutoTokenizer.from_pretrained(INITIAL, local_files_only=True)
    model = AutoModelForSeq2SeqLM.from_pretrained(INITIAL, local_files_only=True,
                                                use_safetensors=True).to(device).train()
    optimizer = torch.optim.AdamW(model.parameters(), lr=TRAINING["lr"], weight_decay=0.01)
    args.output.mkdir(parents=True, exist_ok=True)
    history = []
    usage = {"input_tokens": 0, "padded_input_tokens": 0, "label_tokens": 0, "padded_label_tokens": 0}
    mixed = device == "cuda" and torch.cuda.is_bf16_supported()
    started = time.perf_counter()
    for step in range(1, TRAINING["steps"] + 1):
        pairs = sampler.sample(TRAINING["batch"])
        inputs = tokenizer([p[0] for p in pairs], padding=True, truncation=True,
                           max_length=TRAINING["max_input"], return_tensors="pt").to(device)
        labels = tokenizer(text_target=[p[1] for p in pairs], padding=True, return_tensors="pt")["input_ids"]
        usage["input_tokens"] += int(inputs["attention_mask"].sum())
        usage["padded_input_tokens"] += inputs["input_ids"].numel()
        usage["label_tokens"] += int((labels != tokenizer.pad_token_id).sum())
        usage["padded_label_tokens"] += labels.numel()
        labels[labels == tokenizer.pad_token_id] = -100
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast(device_type=device, dtype=torch.bfloat16, enabled=mixed):
            loss = model(**inputs, labels=labels.to(device)).loss
        if not torch.isfinite(loss):
            raise ValueError(f"Nonfinite loss at step {step}")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        history.append({"step": step, "loss": loss.item()})
        if step == 1 or step % 100 == 0:
            print(json.dumps({"mode": args.mode, "step": step, "loss": loss.item(),
                              "seconds": time.perf_counter() - started}), flush=True)
    if device == "cuda":
        torch.cuda.synchronize()
    seconds = time.perf_counter() - started
    model.save_pretrained(args.output, safe_serialization=True)
    tokenizer.save_pretrained(args.output)
    metadata = {**TRAINING, "max_input": TRAINING["max_input"], "mode": args.mode,
                "corpus_fingerprint": corpus.fingerprint, "initial_checkpoint": str(INITIAL),
                "optimizer": "fresh AdamW lr0.0005, weight_decay0.01, clip1.0; no old optimizer state",
                "initial_training_steps": 4000, "total_gradient_steps": 8000,
                "inputs": protocol["inputs"], "code_hashes": protocol["code_hashes"],
                "model_source": json.loads((INITIAL / "run.json").read_text(encoding="utf-8"))["model_source"],
                "exposures": sampler.counts, "schedule_sha256": sampler.schedule.hexdigest(),
                "corpus_documents_sampled": sum(v > 0 for v in sampler.visits.values()),
                "per_document_visits": sampler.visits, "train_query_pairs": len(sampler.gold),
                "train_claim_ids": [c["id"] for c in claims], "usage": usage,
                "seconds": seconds, "device": device, "bf16_autocast": mixed,
                "gpu": torch.cuda.get_device_name() if device == "cuda" else None,
                "peak_allocated_mib": torch.cuda.max_memory_allocated()/2**20 if device == "cuda" else None,
                "losses": history, "selection": "fixed4000 continuation, no tuning/dev selection"}
    write_json(args.output / "run.json", metadata)
    print(json.dumps({k: metadata[k] for k in ("mode", "seconds", "exposures", "schedule_sha256", "usage")}))


if __name__ == "__main__":
    main()
