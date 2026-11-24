"""SciFact original release adapter. Never expose gold annotations to tools."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import tarfile


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def fingerprint(documents: list[dict]) -> str:
    return hashlib.sha256(json.dumps(documents, sort_keys=True).encode()).hexdigest()


def prepare(archive: Path, output: Path, seed: int = 42) -> dict:
    if output.exists() and any(output.iterdir()):
        raise ValueError("Prepared directory must be empty; choose a new output")
    # Read only these regular files; no extractall, links, or arbitrary archive paths.
    required = {"corpus.jsonl", "claims_train.jsonl", "claims_dev.jsonl"}
    raw = {}
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            name = Path(member.name).name
            if name in required and member.isfile():
                if name in raw or member.size > 100_000_000:
                    raise ValueError("Duplicate/oversized release member")
                raw[name] = [json.loads(line) for line in bundle.extractfile(member) if line.strip()]
    if required != raw.keys():
        raise ValueError("Release does not contain expected original SciFact files")
    corpus = sorted(raw["corpus.jsonl"], key=lambda d: int(d["doc_id"]))
    documents = []
    for index, doc in enumerate(corpus):
        if not isinstance(doc["title"], str) or not isinstance(doc["abstract"], list):
            raise ValueError("Invalid document schema")
        if not all(isinstance(s, str) for s in doc["abstract"]):
            raise ValueError("Abstract must be a list of sentences")
        documents.append({"doc_id": str(doc["doc_id"]), "code": f"{index:05d}",
                          "title": doc["title"], "sentences": doc["abstract"]})
    by_id = {doc["doc_id"]: doc for doc in documents}
    if len(by_id) != len(documents):
        raise ValueError("Duplicate document IDs")
    for name in ("claims_train.jsonl", "claims_dev.jsonl"):
        seen = set()
        for claim in raw[name]:
            if claim["id"] in seen:
                raise ValueError("Duplicate claim IDs")
            seen.add(claim["id"])
            for doc_id, rationales in claim["evidence"].items():
                if doc_id not in by_id:
                    raise ValueError("Gold document missing from corpus")
                for rationale in rationales:
                    if rationale["label"] not in {"SUPPORT", "CONTRADICT"}:
                        raise ValueError("Unknown evidence label")
                    if any(type(i) is not int or not 0 <= i < len(by_id[doc_id]["sentences"])
                           for i in rationale["sentences"]):
                        raise ValueError("Invalid evidence sentence index")
    # Hash normalized query texts so duplicates cannot cross the internal train/tuning split.
    dev = raw["claims_dev.jsonl"]
    dev_texts = {c["claim"].strip().casefold() for c in dev}
    original_training = raw["claims_train.jsonl"]
    removed = [c["id"] for c in original_training if c["claim"].strip().casefold() in dev_texts]
    deduplicated = [c for c in original_training if c["id"] not in removed]
    groups = sorted({c["claim"].strip().casefold() for c in deduplicated})
    random.Random(seed).shuffle(groups)
    tune_texts = set(groups[:max(1, len(groups) // 10)])
    training = [c for c in deduplicated if c["claim"].strip().casefold() not in tune_texts]
    tuning = [c for c in deduplicated if c["claim"].strip().casefold() in tune_texts]
    overlap = {c["claim"].strip().casefold() for c in training} & {c["claim"].strip().casefold() for c in dev}
    if overlap:
        raise ValueError("Training/dev claim text overlap: review release before evaluation")
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "documents.json", documents)
    for name, claims in (("train", training), ("tuning", tuning), ("dev", dev)):
        write_json(output / f"{name}.json", claims)
    audit = {"source": "https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz",
             "archive_sha256": hashlib.file_digest(archive.open("rb"), "sha256").hexdigest(),
             "corpus_fingerprint": fingerprint(documents), "documents": len(documents), "seed": seed,
             "splits": {n: {"claims": len(cs), "with_evidence": sum(bool(c["evidence"]) for c in cs)}
                        for n, cs in (("train", training), ("tuning", tuning), ("dev", dev))},
             "train_dev_text_overlap": len(overlap), "removed_train_claim_ids_matching_dev": removed,
             "test_labels": "not_public_not_loaded",
             "licenses": {"claims": "CC-BY-4.0", "abstracts": "ODC-By-1.0"}}
    write_json(output / "audit.json", audit)
    return audit


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, default=Path("data/raw/data.tar.gz"))
    parser.add_argument("--output", type=Path, default=Path("data/prepared"))
    args = parser.parse_args()
    print(json.dumps(prepare(args.archive, args.output), indent=2))
