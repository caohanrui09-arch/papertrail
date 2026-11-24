"""Corpus-only textual DocIDs and receipts for an unchanged DSI trainer."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import shutil

from .data import write_json
from .retrieval import Corpus, DocumentTrie
from .train import training_pairs


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def title_documents(documents: list[dict], tokenizer: object, prefix_tokens: int = 12) -> list[dict]:
    if type(prefix_tokens) is not int or prefix_tokens < 1:
        raise ValueError("Positive title prefix length required")
    result = []
    for doc in documents:
        tokens = [t for t in tokenizer.encode(doc["title"], add_special_tokens=False)
                  if t not in tokenizer.all_special_ids][:prefix_tokens]
        prefix = tokenizer.decode(tokens, skip_special_tokens=True, clean_up_tokenization_spaces=False)
        prefix = prefix.strip() or "document"
        raw = prefix + " | " + doc["code"]
        code = tokenizer.decode(tokenizer.encode(raw, add_special_tokens=False),
                                skip_special_tokens=True, clean_up_tokenization_spaces=False).strip()
        # Search uses HF's default cleanup. Reject changes rather than silently miss a lookup.
        roundtrip = tokenizer.decode(tokenizer.encode(code, add_special_tokens=False),
                                     skip_special_tokens=True).strip()
        if code != roundtrip or not code.endswith(" | " + doc["code"]):
            raise ValueError(f"DocID is not stable through model decoding: {doc['doc_id']}")
        result.append({**doc, "code": code})
    if len({d["doc_id"] for d in result}) != len(result) or len({d["code"] for d in result}) != len(result):
        raise ValueError("Document identifiers must be unique")
    DocumentTrie(tokenizer, [d["code"] for d in result])
    return result


def sampling_receipt(corpus: Corpus, claims: list[dict], tokenizer: object,
                     steps: int = 4000, batch: int = 8, seed: int = 42,
                     query_fraction: float = 0.5, max_input: int = 160) -> dict:
    """Replay trainer's sampling without forward passes; only train annotations read."""
    if steps < 1 or batch < 1 or not 0 < query_fraction < 1:
        raise ValueError("Invalid training schedule")
    indexing, queries = training_pairs(corpus, claims)
    pools = {"index": indexing, "query": queries}
    lengths = {}
    for name, pairs in pools.items():
        ins = tokenizer([p[0] for p in pairs], truncation=True, max_length=max_input)["input_ids"]
        outs = tokenizer(text_target=[p[1] for p in pairs])["input_ids"]
        lengths[name] = [(len(x), len(y)) for x, y in zip(ins, outs)]
    rng = random.Random(seed)
    digest = hashlib.sha256()
    counts = {"index": 0, "query": 0}
    input_tokens = label_tokens = padded_input_tokens = padded_label_tokens = 0
    for _ in range(steps):
        sizes = []
        for _ in range(batch):
            task = "query" if rng.random() < query_fraction else "index"
            position = rng.randrange(len(pools[task]))
            digest.update(f"{task}:{position}\n".encode())
            counts[task] += 1
            sizes.append(lengths[task][position])
        input_tokens += sum(x for x, y in sizes)
        label_tokens += sum(y for x, y in sizes)
        padded_input_tokens += max(x for x, y in sizes) * batch
        padded_label_tokens += max(y for x, y in sizes) * batch
    target_lengths = [len(tokenizer.encode(d["code"])) for d in corpus.documents]
    return {"steps": steps, "batch": batch, "seed": seed, "query_fraction": query_fraction,
            "max_input": max_input, "exposures": counts, "schedule_sha256": digest.hexdigest(),
            "input_tokens": input_tokens, "label_tokens": label_tokens,
            "padded_input_tokens": padded_input_tokens, "padded_label_tokens": padded_label_tokens,
            "catalog_target_tokens": {"min": min(target_lengths), "max": max(target_lengths),
                                     "mean": sum(target_lengths) / len(target_lengths)},
            "train_claim_ids": [c["id"] for c in claims], "train_query_pairs": len(queries),
            "accounting": "Exact seeded sampling and token lengths, not measured GPU FLOPs"}


def prepare(source: Path, output: Path, tokenizer: object, model_path: Path,
            prefix_tokens: int = 12) -> dict:
    if output.exists() and any(output.iterdir()):
        raise ValueError("Refusing to overwrite identifier data")
    original = Corpus(source / "documents.json")
    converted = title_documents(original.documents, tokenizer, prefix_tokens)
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "documents.json", converted)
    for split in ("train", "tuning", "dev"):
        shutil.copyfile(source / f"{split}.json", output / f"{split}.json")
    transformed = Corpus(output / "documents.json")
    train = json.loads((source / "train.json").read_text(encoding="utf-8"))
    receipts = {"numeric": sampling_receipt(original, train, tokenizer),
                "title": sampling_receipt(transformed, train, tokenizer)}
    assert receipts["numeric"]["schedule_sha256"] == receipts["title"]["schedule_sha256"]
    audit = {"construction": f"first{prefix_tokens}_non_special_T5_title_tokens_then_pipe_then_original_numeric_code",
             "prefix_tokens": prefix_tokens, "documents": len(converted),
             "original_fingerprint": original.fingerprint, "title_fingerprint": transformed.fingerprint,
             "model_source_sha256": sha256(model_path / "source.json"),
             "original_files": {p.name: sha256(p) for p in source.glob("*.json")},
             "variant_files": {p.name: sha256(p) for p in output.glob("*.json")},
             "labels_used_in_mapping": False, "training_receipts": receipts}
    write_json(output / "identifier-audit.json", audit)
    return audit


if __name__ == "__main__":
    from transformers import AutoTokenizer
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("data/prepared"))
    parser.add_argument("--output", type=Path, default=Path("data/stage4-title"))
    parser.add_argument("--model", type=Path, default=Path(".cache/models/t5-small"))
    args = parser.parse_args()
    audit = prepare(args.source, args.output, AutoTokenizer.from_pretrained(args.model, local_files_only=True), args.model)
    print(json.dumps({"documents": audit["documents"], "training_receipts": {
        k: {a: b for a, b in v.items() if a != "train_claim_ids"} for k, v in audit["training_receipts"].items()}}, indent=2))
