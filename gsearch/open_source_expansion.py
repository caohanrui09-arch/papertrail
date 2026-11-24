"""Thin adapters for unmodified MIT PyTerrier Doc2Query-- components."""
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pyterrier as pt

from .retrieval import BM25, Corpus


ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "third_party/pyterrier_doc2query_upstream"


def verify_upstream() -> dict:
    audit = json.loads((ROOT / "reports/stage6/upstream-audit.json").read_text(encoding="utf-8"))
    for item in audit["direct_reuse"]["files"]:
        data = (VENDOR / item["path"]).read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if actual != item["git_blob_sha"]:
            raise ValueError(f"Upstream file changed: {item['path']}")
    return audit


verify_upstream()
sys.path.insert(0, str(VENDOR))
from pyterrier_doc2query import QueryFilter, QueryScorer  # noqa: E402


class FrozenPairScorer(pt.Transformer):
    """Preserve upstream QueryScorer's row/qid order, using our cached HF classifier."""
    def __init__(self, model: object):
        self.model = model

    def transform(self, frame: pd.DataFrame) -> pd.DataFrame:
        scores = self.model.logits(frame["query"].tolist(), frame["text"].tolist()).flatten().tolist()
        if len(scores) != len(frame) or not np.isfinite(scores).all():
            raise ValueError("Classifier returned missing or nonfinite scores")
        return frame.assign(score=scores)


def source_frame(corpus: Corpus, records: list[dict]) -> pd.DataFrame:
    by_id = {r["doc_id"]: r for r in records}
    if len(by_id) != len(records) or set(by_id) != set(corpus.by_id):
        raise ValueError("Generated queries must cover the original corpus exactly")
    rows = []
    for doc in corpus.documents:
        queries = by_id[doc["doc_id"]]["queries"]
        if not queries or any(not isinstance(q, str) or not q.strip() or "\n" in q or "\r" in q for q in queries):
            raise ValueError("Expected nonempty queries without newline ambiguity")
        rows.append({"docno": doc["doc_id"], "text": doc["title"] + " " + " ".join(doc["sentences"]),
                     "querygen": "\n".join(queries)})
    return pd.DataFrame(rows)


def score_sources(corpus: Corpus, records: list[dict], model: object) -> list[dict]:
    # The upstream class owns flattening and grouping queries back to documents.
    scored = QueryScorer(FrozenPairScorer(model))(source_frame(corpus, records))
    return [{"doc_id": row.docno, "queries": row.querygen.split("\n"),
             "scores": [float(v) for v in row.querygen_score]} for row in scored.itertuples(index=False)]


def filtered_queries(corpus: Corpus, scored: list[dict], threshold: float) -> dict[str, list[str]]:
    records = [{"doc_id": r["doc_id"], "queries": r["queries"]} for r in scored]
    frame = source_frame(corpus, records)
    by_id = {r["doc_id"]: r for r in scored}
    scores = []
    for doc_id, querygen in zip(frame["docno"], frame["querygen"]):
        values = np.asarray(by_id[doc_id]["scores"], dtype=np.float64)
        if len(values) != len(querygen.split("\n")) or not np.isfinite(values).all():
            raise ValueError("Query and score lists differ or include nonfinite scores")
        scores.append(values)
    frame = frame.assign(querygen_score=scores)
    # Use upstream >= threshold semantics verbatim; append=False keeps evidence text separate.
    result = QueryFilter(t=threshold, append=False)(frame)
    return {row.docno: row.querygen.split("\n") if row.querygen else [] for row in result.itertuples(index=False)}


def expansion_index(corpus: Corpus, queries: dict[str, list[str]]) -> tuple[BM25, dict]:
    if set(queries) != set(corpus.by_id):
        raise ValueError("Expansion must retain every original document")
    retriever = BM25(corpus)
    # Reuse the project's SQLite FTS5 BM25, preserving the original title2/body1 fields.
    retriever.db.executemany("UPDATE docs SET body=? WHERE doc_id=?", [
        (" ".join([*d["sentences"], *queries[d["doc_id"]]]), d["doc_id"]) for d in corpus.documents])
    retriever.db.commit()
    retriever.db.execute("INSERT INTO docs(docs) VALUES('optimize')")
    retriever.db.commit()
    pages = retriever.db.execute("PRAGMA page_count").fetchone()[0]
    free = retriever.db.execute("PRAGMA freelist_count").fetchone()[0]
    size = retriever.db.execute("PRAGMA page_size").fetchone()[0]
    retriever.name = "sqlite_bm25_doc2query_expansion"
    audit = {"documents": len(corpus.documents), "appended_queries": sum(len(q) for q in queries.values()),
             "documents_with_expansion": sum(bool(q) for q in queries.values()),
             "sqlite_allocated_bytes": pages * size, "sqlite_nonfree_bytes": (pages - free) * size,
             "original_evidence_corpus_fingerprint": corpus.fingerprint,
             "title_weight": 2, "body_weight": 1,
             "evidence_source": "original corpus only; synthetic text stays in FTS index"}
    return retriever, audit
