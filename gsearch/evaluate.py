"""Document-level retrieval evaluation. Unjudged claims are reported separately."""
import argparse
import json
import math
from pathlib import Path
import time

from .data import write_json
from .retrieval import BM25, Corpus, GenerativeRetriever, Hybrid


def metrics(predictions: list[str | None], relevant: set[str], k: int) -> dict[str, float]:
    if not relevant:
        raise ValueError("Recall/NDCG require a non-empty judged relevant set")
    seen = set()
    ranks = []
    for rank, doc in enumerate(predictions[:k], 1):
        if doc in relevant and doc not in seen:
            ranks.append(rank)
        seen.add(doc)
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(k, len(relevant)) + 1))
    return {"recall": len(ranks) / len(relevant), "hit": float(bool(ranks)),
            "mrr": 1 / ranks[0] if ranks else 0.0,
            "ndcg": sum(1 / math.log2(r + 1) for r in ranks) / ideal}


def evaluate(retriever: object, claims: list[dict], k: int = 10) -> dict:
    rows = []
    ignored = 0
    # Warm-up excluded from timings; no gold documents passed to the searcher.
    if claims:
        retriever.search(claims[0]["claim"], k)
    for claim in claims:
        relevant = set(claim["evidence"])
        if not relevant:
            ignored += 1
            continue
        start = time.perf_counter()
        hits = retriever.search(claim["claim"], k)
        elapsed = time.perf_counter() - start
        ids = [h["doc_id"] for h in hits]
        rows.append({"claim_id": claim["id"], "query": claim["claim"], "relevant": sorted(relevant),
                     "predictions": hits, "seconds": elapsed, **metrics(ids, relevant, k),
                     "valid_slots": sum(d is not None for d in ids),
                     "unique_slots": len({d for d in ids if d is not None})})
    summary = {name + f"@{k}": sum(r[name] for r in rows) / len(rows) if rows else None
               for name in ("recall", "hit", "mrr", "ndcg")}
    summary.update({"judged_queries": len(rows), "no_evidence_queries_excluded": ignored,
                    "valid_slot_rate": sum(r["valid_slots"] for r in rows) / (len(rows) * k) if rows else None,
                    "unique_slot_rate": sum(r["unique_slots"] for r in rows) / (len(rows) * k) if rows else None,
                    "mean_seconds": sum(r["seconds"] for r in rows) / len(rows) if rows else None})
    return {"retriever": retriever.name, "k": k, "summary": summary, "queries": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("data/prepared"))
    parser.add_argument("--split", choices=["tuning", "dev"], default="tuning")
    parser.add_argument("--retriever", choices=["bm25", "dsi", "hybrid"], default="bm25")
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--beam", type=int, default=10)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    corpus = Corpus(args.data / "documents.json")
    searcher = BM25(corpus)
    if args.retriever != "bm25":
        if args.checkpoint is None:
            parser.error("--checkpoint is required for dsi/hybrid")
        neural = GenerativeRetriever(corpus, args.checkpoint, args.beam)
        searcher = neural if args.retriever == "dsi" else Hybrid(searcher, neural)
    claims = json.loads((args.data / f"{args.split}.json").read_text(encoding="utf-8"))
    if args.limit:
        claims = claims[:args.limit]
    result = evaluate(searcher, claims, args.k)
    result.update({"split": args.split, "limit": args.limit, "corpus_fingerprint": corpus.fingerprint,
                   "checkpoint": str(args.checkpoint), "beam": args.beam,
                   "timing": "batch1, warmup excluded, tokenization+decode+lookup included"})
    write_json(args.output, result)
    print(json.dumps(result["summary"], indent=2))
