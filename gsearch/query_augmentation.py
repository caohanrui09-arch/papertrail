"""Corpus-only doc2query generation; no claim or annotation files are opened."""
import argparse
import json
from pathlib import Path
import time

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

from .data import write_json
from .identifiers import sha256
from .retrieval import Corpus


TEACHER = Path(".cache/models/msmarco-t5-small-v1")
GENERATION = {"batch": 16, "max_input": 320, "max_new_tokens": 64,
              "num_return_sequences": 2, "top_p": 0.95, "top_k": 0, "seed": 20261025}


def normalize(text: str) -> str:
    return " ".join(text.split()).casefold()


def accepted_queries(document: dict, candidates: list[str]) -> dict:
    accepted, seen = [], set()
    for text in candidates:
        normalized = normalize(text)
        if normalized and normalized not in seen:
            accepted.append(text.strip())
            seen.add(normalized)
    fallback = not accepted
    if fallback:
        accepted = [document["title"].strip() or " ".join(document["sentences"]).strip() or "scientific document"]
    return {"doc_id": document["doc_id"], "raw_candidates": candidates,
            "queries": accepted, "fallback": fallback,
            "provenance": "weak_doc2query_source_association_not_verified_relevance"}


def teacher_state() -> dict:
    return {p.name: sha256(p) for p in TEACHER.iterdir()
            if p.name == "model.safetensors" or p.suffix in (".json", ".model")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--documents", type=Path, default=Path("data/stage4-title/documents.json"))
    parser.add_argument("--output", type=Path, default=Path("data/stage5-queries"))
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    torch.set_num_threads(4)
    corpus = Corpus(args.documents)
    manifest = {"corpus_fingerprint": corpus.fingerprint, "documents_sha256": sha256(args.documents),
                "teacher": teacher_state(), "generation": GENERATION,
                "code_sha256": sha256(Path(__file__)), "input": "title plus all abstract sentences, no claims"}
    path = args.output / "manifest.json"
    if path.exists():
        if not args.resume or json.loads(path.read_text(encoding="utf-8")) != manifest:
            raise ValueError("Existing generation requires identical manifest and --resume")
    elif args.resume or args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Missing manifest or nonempty unregistered output")
    else:
        write_json(path, manifest)
    if (args.output / "queries.json").exists():
        raise ValueError("Completed query artifact is immutable")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    tokenizer = AutoTokenizer.from_pretrained(TEACHER, local_files_only=True)
    model = AutoModelForSeq2SeqLM.from_pretrained(TEACHER, local_files_only=True,
                                                use_safetensors=True, trust_remote_code=False).to(device).eval()
    all_records, batches = [], []
    started = time.perf_counter()
    for offset in range(0, len(corpus.documents), GENERATION["batch"]):
        docs = corpus.documents[offset:offset + GENERATION["batch"]]
        output = args.output / "batches" / f"{offset:05d}.json"
        if output.exists():
            if not args.resume:
                raise ValueError("Existing batch without resume")
            result = json.loads(output.read_text(encoding="utf-8"))
            if [r["doc_id"] for r in result["records"]] != [d["doc_id"] for d in docs]:
                raise ValueError("Resume document order mismatch")
        else:
            torch.manual_seed(GENERATION["seed"] + offset)
            if device == "cuda":
                torch.cuda.manual_seed_all(GENERATION["seed"] + offset)
            inputs = tokenizer([d["title"] + " " + " ".join(d["sentences"]) for d in docs],
                               truncation=True, max_length=GENERATION["max_input"], padding=True,
                               return_tensors="pt").to(device)
            begin = time.perf_counter()
            with torch.inference_mode():
                outputs = model.generate(**inputs, do_sample=True, num_beams=1,
                                         num_return_sequences=GENERATION["num_return_sequences"],
                                         top_p=GENERATION["top_p"], top_k=GENERATION["top_k"],
                                         max_new_tokens=GENERATION["max_new_tokens"])
            outputs = outputs.cpu()
            texts = tokenizer.batch_decode(outputs, skip_special_tokens=True)
            records = [accepted_queries(d, texts[2*i:2*i+2]) for i, d in enumerate(docs)]
            result = {"records": records, "seconds": time.perf_counter() - begin,
                      "encoder_input_tokens": int(inputs["attention_mask"].sum()),
                      "padded_encoder_input_tokens": inputs["input_ids"].numel(),
                      "output_tokens": int((outputs != tokenizer.pad_token_id).sum()),
                      "padded_decoder_slots": outputs.shape[0] * (outputs.shape[1] - 1)}
            write_json(output, result)
        all_records.extend(result["records"])
        batches.append({k: v for k, v in result.items() if k != "records"})
        if offset == 0 or offset % 320 == 0:
            print(json.dumps({"documents": len(all_records), "total": len(corpus.documents),
                              "seconds_this_invocation": time.perf_counter() - started}), flush=True)
    if len(all_records) != len(corpus.documents) or len({r["doc_id"] for r in all_records}) != len(all_records):
        raise ValueError("Incomplete or repeated generation documents")
    write_json(args.output / "queries.json", all_records)
    audit = {"manifest_sha256": sha256(path), "queries_sha256": sha256(args.output / "queries.json"),
             "documents": len(all_records), "raw_candidates": sum(len(r["raw_candidates"]) for r in all_records),
             "accepted_queries": sum(len(r["queries"]) for r in all_records),
             "fallback_documents": sum(r["fallback"] for r in all_records),
             "device": device, "gpu": torch.cuda.get_device_name() if device == "cuda" else None,
             "peak_allocated_mib": torch.cuda.max_memory_allocated() / 2**20 if device == "cuda" else None,
             "batches": batches, "generation_seconds": sum(b["seconds"] for b in batches),
             "labels_read": False}
    write_json(args.output / "audit.json", audit)
    print(json.dumps({k: v for k, v in audit.items() if k != "batches"}, indent=2), flush=True)


if __name__ == "__main__":
    main()
