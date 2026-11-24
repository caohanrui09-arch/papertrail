"""Matched raw-token targets; HF owns the training/optimization loop."""
import argparse
import hashlib
import importlib.metadata as metadata
import inspect
import json
from pathlib import Path
import random
import time

import torch
from torch.utils.data import Dataset, SequentialSampler
from transformers import (AutoModelForSeq2SeqLM, AutoTokenizer, DataCollatorForSeq2Seq,
                          Seq2SeqTrainer, Seq2SeqTrainingArguments, TrainerCallback, set_seed)

from .data import write_json
from .identifiers import sha256
from .prefix_decoder import PrefixIndex
from .retrieval import Corpus
from .train import training_pairs
from .train_query_aug import checkpoint_hashes


ROOT = Path("reports/stage8")
DATA = Path("data/stage4-title")
TARGETS = Path("data/stage8-targets")
BASE = Path(".cache/models/t5-small")
RUNS = {m: Path(f"runs/t5-stage8-{m}-4000-seed42") for m in ("full", "short")}
TRAINING = {"steps": 4000, "batch": 8, "max_input": 160, "seed": 42,
            "query_fraction": 0.5, "lr": 0.0005, "weight_decay": 0.01,
            "gradient_accumulation_steps": 1, "max_grad_norm": 1.0,
            "lr_scheduler_type": "constant", "adam_betas": [0.9, 0.999], "adam_epsilon": 1e-8}


def read(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def prepare() -> None:
    if TARGETS.exists():
        raise ValueError("Refusing to overwrite frozen target data")
    corpus = Corpus(DATA / "documents.json")
    tokenizer = AutoTokenizer.from_pretrained(BASE, local_files_only=True)
    indexing, queries = training_pairs(corpus, read(DATA / "train.json"))
    examples = []
    for role, pairs in (("index", indexing), ("query", queries)):
        encoded = tokenizer([p[0] for p in pairs], truncation=True, max_length=160)
        examples.extend({"role": role, "doc_id": corpus.by_code[pair[1]],
                         "input_ids": encoded["input_ids"][i],
                         "attention_mask": encoded["attention_mask"][i]}
                        for i, pair in enumerate(pairs))
    rng, digest, schedule = random.Random(42), hashlib.sha256(), []
    for _ in range(TRAINING["steps"] * TRAINING["batch"]):
        role = "query" if rng.random() < 0.5 else "index"
        position = rng.randrange(len(queries) if role == "query" else len(indexing))
        digest.update(f"{role}:{position}\n".encode())
        schedule.append(position + (len(indexing) if role == "query" else 0))
    write_json(TARGETS / "common.json", {"examples": examples, "schedule": schedule,
               "task_position_schedule_sha256": digest.hexdigest(),
               "exposures": {r: sum(examples[i]["role"] == r for i in schedule) for r in ("index", "query")}})
    for mode in RUNS:
        index = PrefixIndex(corpus, tokenizer, mode == "short")
        record = {"stats": index.stats, "aliases": index.aliases}
        if record != read(Path(f"reports/stage7/{mode}-index.json")):
            raise ValueError("Previously verified ZeroGR aliases differ")
        write_json(TARGETS / f"{mode}.json", record)
    write_json(TARGETS / "audit.json", {"source": "static corpus + original train.json only",
               "train_claims": len(read(DATA / "train.json")),
               "corpus_fingerprint": corpus.fingerprint, "raw_labels_including_eos": True,
               "holdout_labels_read_by_preparation": False})


class AlignedDataset(Dataset):
    def __init__(self, common: dict, aliases: list[dict]):
        self.examples, self.schedule = common["examples"], common["schedule"]
        self.labels = {r["doc_id"]: r["token_ids"] for r in aliases}
        if len(self.labels) != len(aliases) or any(e["doc_id"] not in self.labels for e in self.examples):
            raise ValueError("Incomplete or ambiguous raw target mapping")

    def __len__(self) -> int:
        return len(self.schedule)

    def __getitem__(self, position: int) -> dict:
        row = self.examples[self.schedule[position]]
        return {"input_ids": list(row["input_ids"]), "attention_mask": list(row["attention_mask"]),
                "labels": list(self.labels[row["doc_id"]]), "_position": position}


class OrderedSeq2SeqTrainer(Seq2SeqTrainer):
    """Only replace random sampling with Torch's existing sequential sampler."""
    def _get_train_sampler(self, train_dataset: Dataset | None = None) -> SequentialSampler:
        return SequentialSampler(self.train_dataset if train_dataset is None else train_dataset)


class AuditCollator:
    def __init__(self, collator: DataCollatorForSeq2Seq):
        self.collator, self.positions, self.batches = collator, 0, 0
        self.usage = {k: 0 for k in ("input_tokens", "padded_input_tokens", "label_tokens", "padded_label_tokens")}
        self.digest = hashlib.sha256()

    def __call__(self, features: list[dict]) -> dict:
        positions = [f["_position"] for f in features]
        if positions != list(range(self.positions, self.positions + len(features))):
            raise ValueError("Trainer changed the frozen sample order")
        self.positions += len(features)
        self.batches += 1
        clean = [{k: v for k, v in f.items() if k != "_position"} for f in features]
        for f in clean:
            self.digest.update((json.dumps(f, sort_keys=True, separators=(",", ":")) + "\n").encode())
        batch = self.collator(clean)
        self.usage["input_tokens"] += int(batch["attention_mask"].sum())
        self.usage["padded_input_tokens"] += batch["input_ids"].numel()
        self.usage["label_tokens"] += int((batch["labels"] != -100).sum())
        self.usage["padded_label_tokens"] += batch["labels"].numel()
        return batch


class Progress(TrainerCallback):
    def on_log(self, args: object, state: object, control: object, logs: dict | None = None, **kwargs: object) -> None:
        print(json.dumps({"step": state.global_step, **(logs or {})}), flush=True)


def engine_state() -> dict:
    import transformers.trainer as trainer_module
    import transformers.trainer_seq2seq as seq_module
    import transformers.data.data_collator as collator_module
    return {"packages": {n: metadata.version(n) for n in
                ("torch", "numpy", "transformers", "accelerate", "sentencepiece")},
            "implementation_sha256": {m.__name__: sha256(Path(inspect.getfile(m)))
                for m in (trainer_module, seq_module, collator_module)}}


def train(mode: str) -> None:
    from .benchmark_target_alignment import check_plan
    check_plan()
    output = RUNS[mode]
    if output.exists():
        raise ValueError("Refusing to overwrite a training run")
    set_seed(42)
    torch.set_num_threads(4)
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise ValueError("Frozen protocol requires existing CUDA BF16 runtime")
    tokenizer = AutoTokenizer.from_pretrained(BASE, local_files_only=True)
    model = AutoModelForSeq2SeqLM.from_pretrained(BASE, local_files_only=True, use_safetensors=True)
    dataset = AlignedDataset(read(TARGETS / "common.json"), read(TARGETS / f"{mode}.json")["aliases"])
    collator = AuditCollator(DataCollatorForSeq2Seq(tokenizer, model=model, label_pad_token_id=-100))
    arguments = Seq2SeqTrainingArguments(
        output_dir=str(output), max_steps=4000, per_device_train_batch_size=8,
        gradient_accumulation_steps=1, learning_rate=0.0005, weight_decay=0.01,
        lr_scheduler_type="constant", warmup_steps=0, max_grad_norm=1.0,
        seed=42, data_seed=42, bf16=True, tf32=False, eval_strategy="no", save_strategy="no",
        logging_steps=50, logging_first_step=True, logging_nan_inf_filter=False,
        report_to="none", disable_tqdm=True, dataloader_num_workers=0,
        dataloader_pin_memory=False, remove_unused_columns=False, save_safetensors=True)
    # Preserve the original AdamW update rule, including decay on all trainable parameters.
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.0005, weight_decay=0.01,
                                 betas=(0.9, 0.999), eps=1e-8)
    trainer = OrderedSeq2SeqTrainer(model=model, args=arguments, train_dataset=dataset,
                 data_collator=collator, processing_class=tokenizer, optimizers=(optimizer, None),
                 callbacks=[Progress()])
    trainer.model_accepts_loss_kwargs = False  # T5's native mean token CE, no custom loss/scaling.
    torch.cuda.reset_peak_memory_stats()
    torch.cuda.synchronize()
    started = time.perf_counter()
    result = trainer.train()
    torch.cuda.synchronize()
    elapsed = time.perf_counter() - started
    if (trainer.state.global_step != 4000 or collator.positions != 32000 or collator.batches != 4000
            or any(not torch.isfinite(torch.tensor(r["loss"])) for r in trainer.state.log_history if "loss" in r)):
        raise ValueError("Incomplete training or nonfinite logged loss")
    trainer.save_model()
    trainer.save_state()
    tokenizer.save_pretrained(output)
    write_json(output / "run.json", {"mode": mode, "corpus_fingerprint": Corpus(DATA / "documents.json").fingerprint,
          "max_input": 160, "training": TRAINING, "engine": engine_state(),
          "initial_assets": checkpoint_hashes(BASE), "plan_sha256": sha256(ROOT / "plan.json"),
          "common_sha256": sha256(TARGETS / "common.json"), "target_sha256": sha256(TARGETS / f"{mode}.json"),
          "task_position_schedule_sha256": read(TARGETS / "common.json")["task_position_schedule_sha256"],
          "observed_steps": trainer.state.global_step, "observed_samples": collator.positions,
          "observed_batches": collator.batches, "observed_token_batch_sha256": collator.digest.hexdigest(),
          "usage": collator.usage, "seconds": elapsed, "trainer_metrics": result.metrics,
          "device": torch.cuda.get_device_name(), "bf16": True, "tf32": False,
          "peak_allocated_mib": torch.cuda.max_memory_allocated() / 2**20,
          "trainable_parameters": sum(p.numel() for p in model.parameters() if p.requires_grad),
          "selection": "fixed 4000 steps; no tuning/dev labels in training; native mean CE"})
    print(json.dumps({"mode": mode, "seconds": elapsed, "usage": collator.usage}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("prepare", "full", "short"), required=True)
    args = parser.parse_args()
    prepare() if args.mode == "prepare" else train(args.mode)


if __name__ == "__main__":
    main()
