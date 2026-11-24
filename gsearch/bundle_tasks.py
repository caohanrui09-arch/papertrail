"""Controlled two-claim composition. Public tasks contain no evidence or gold labels."""
import argparse
import hashlib
import json
from pathlib import Path
import random

from .data import write_json


def construct_tasks(claims: list[dict], split: str, seed: int) -> tuple[list[dict], dict]:
    unique = {}
    for claim in sorted(claims, key=lambda c: c["id"]):
        unique.setdefault(claim["claim"].strip().casefold(), claim)
    ordered = sorted(unique.values(), key=lambda c: c["id"])
    random.Random(seed).shuffle(ordered)
    public, gold = [], {}
    for index in range(len(ordered) // 2):
        members = ordered[2 * index:2 * index + 2]
        task_id = f"{split}-{index:03d}"
        public.append({"task_id": task_id, "claims": {key: c["claim"] for key, c in zip(("A", "B"), members)},
                       "instruction": "Check A and B independently and return a separate verdict and citations for each. Do not transfer evidence between claims."})
        gold[task_id] = {key: {"source_claim_id": c["id"], "claim": c["claim"], "evidence": c["evidence"]}
                         for key, c in zip(("A", "B"), members)}
    return public, gold


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("data/prepared"))
    parser.add_argument("--output", type=Path, default=Path("data/stage3-bundles"))
    parser.add_argument("--seed", type=int, default=20261025)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Refusing to overwrite composed tasks")
    audit = {"seed": args.seed, "task_type": "controlled_composition_not_natural_multihop",
             "selection": "normalized-text deduplication, fixed-seed shuffle, pair consecutive claims; no label/result filtering",
             "splits": {}}
    for split in ("tuning", "dev"):
        source = args.data / f"{split}.json"
        claims = json.loads(source.read_text(encoding="utf-8"))
        public, gold = construct_tasks(claims, split, args.seed)
        write_json(args.output / f"{split}-public.json", public)
        write_json(args.output / f"{split}-gold.json", gold)
        audit["splits"][split] = {"tasks": len(public), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                                  "public_sha256": hashlib.sha256((args.output / f"{split}-public.json").read_bytes()).hexdigest(),
                                  "gold_sha256": hashlib.sha256((args.output / f"{split}-gold.json").read_bytes()).hexdigest()}
    write_json(args.output / "audit.json", audit)
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
