"""Build a new source-backed catalog without modifying frozen stage9 data."""
from datetime import datetime
import json
from pathlib import Path

import pandas as pd

from .data import write_json
from .identifiers import sha256
from .metadata_fetch import ROOT, CATALOG, read
from .paper_identity import canonical_id


OUTPUT = Path("data/stage10-catalog")


def valid_date(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def source_valid(record: dict) -> bool:
    provenance = record.get("provenance", {})
    path = Path(provenance.get("raw_path", "__absent__"))
    return path.is_file() and sha256(path) == provenance.get("raw_sha256") and canonical_id(record["source_url"]) == record["doc_id"]


def source_text_matches(record: dict) -> bool:
    if not source_valid(record):
        return False
    body = Path(record["provenance"]["raw_path"]).read_bytes()
    if record["source_kind"] == "official_arxiv_api":
        from .metadata_fetch import upstream
        feed = upstream()._feed.parse(body)
        return any(canonical_id(r.entry_id) == record["doc_id"] and r.title == record["title"]
                   and r.summary == record["abstract"] for r in feed.results)
    payload = json.loads(body)
    rows = payload if isinstance(payload, list) else [r["row"] for r in payload.get("rows", [])]
    return any(canonical_id(r["paper_id"]) == record["doc_id"] and r.get("title") == record["title"]
               and r.get("abstract") == record["abstract"] for r in rows)


def collected_records() -> dict[str, dict]:
    records = {}
    # Prefer pinned snapshot to unpinned filter responses; official live API has highest priority.
    groups = [sorted((ROOT/"batches/mirror").glob("*.json")), sorted((ROOT/"parquet-groups").glob("*.json")),
              sorted((ROOT/"batches/arxiv").glob("*.json"))]
    for files in groups:
        for path in files:
            for row in read(path).get("records", []):
                if not source_valid(row):
                    raise ValueError("Source response integrity or identity mismatch")
                records[row["doc_id"]] = row
    return records


def build(output: Path = OUTPUT) -> dict:
    if output.exists():
        raise ValueError("Refusing to overwrite enriched catalog")
    original = read(CATALOG)
    canonical = [canonical_id(d) for d in original]
    canonical_set = set(canonical)
    if len(original) != 2048 or len(set(canonical)) != 2048:
        raise ValueError("Expected 2048 unique candidate identities")
    collected = collected_records()
    if set(collected)-set(canonical):
        raise ValueError("Acquisition introduced out-of-catalog papers")
    metadata, documents, failures, aliases = [], [], [], []
    for raw_id, identity in zip(original, canonical):
        record = dict(collected.get(identity, {"doc_id": identity, "paper_key": "arxiv:"+identity,
                     "title": None, "abstract": None, "published_at": None, "updated_at": None,
                     "landing_url": "https://arxiv.org/abs/"+identity,
                     "fetch_status": "not_acquired", "failure_reason": "No successful source record; see network attempt receipts"}))
        record["original_catalog_id"] = raw_id
        populated = lambda key: isinstance(record.get(key), str) and bool(record[key].strip())
        flags = {"has_title": populated("title"), "has_abstract": populated("abstract"),
                 "has_published_date": valid_date(record.get("published_at")),
                 "has_source": source_valid(record) if record.get("source_url") else False}
        flags["searchable"] = flags["has_abstract"] and flags["has_title"] and flags["has_source"]
        flags["citable"] = flags["has_abstract"] and flags["has_source"]
        record["coverage"] = flags
        record.setdefault("fetch_status", "acquired")
        metadata.append(record)
        aliases.append({"original_catalog_id": raw_id, "canonical_doc_id": identity, "paper_key": "arxiv:"+identity,
                        "source_url": record.get("source_url"), "landing_url": record["landing_url"],
                        "version": record.get("version"), "identity_policy": "base ID identifies paper; version is separate, never guessed"})
        if flags["searchable"]:
            documents.append({"doc_id": identity, "code": identity, "title": record["title"],
                "sentences": [record["abstract"]], "metadata": record, "abstract_unit": "whole original abstract, not segmented evidence"})
        if not all(flags.values()):
            failures.append({"doc_id": identity, "missing_fields": [k for k, v in flags.items() if not v],
                             "reason": record.get("failure_reason", "Source metadata field absent or invalid")})
    output.mkdir(parents=True)
    write_json(output/"metadata.json", metadata)
    write_json(output/"documents.json", documents)
    write_json(output/"catalog.json", canonical)
    write_json(output/"identity-map.json", aliases)
    write_json(output/"failures.json", failures)
    counts = {k: sum(r["coverage"][k] for r in metadata) for k in metadata[0]["coverage"]}
    joins, views = {}, []
    interaction_aliases = {}
    def normalize_optional(value: str) -> str | None:
        try:
            return canonical_id(value)
        except ValueError:
            return None
    for split in ("train", "tuning", "dev"):
        path = Path("data/stage9-recommendation")/(split+".csv")
        frame = pd.read_csv(path, dtype={"arxiv_id": str, "user_id": str})
        unique_mapping = {value: normalize_optional(value) for value in frame.arxiv_id.unique()}
        mapped = frame.arxiv_id.map(unique_mapping)
        selected = frame[mapped.isin(canonical)].copy()
        selected["original_arxiv_id"] = selected["arxiv_id"]
        selected["canonical_doc_id"] = selected.arxiv_id.map(unique_mapping)
        selected["paper_key"] = "arxiv:"+selected["canonical_doc_id"]
        selected["split"] = split
        if not set(selected.canonical_doc_id).issubset(canonical) or selected.canonical_doc_id.isna().any():
            raise ValueError("Interaction mapping lost candidates")
        interaction_aliases.update({raw: identity for raw, identity in unique_mapping.items() if identity in canonical_set})
        joins[split] = {"all_rows": len(frame), "candidate_rows": len(selected), "outside_catalog_rows": len(frame)-len(selected),
                       "invalid_id_rows_outside_scope": int(mapped.isna().sum()),
                       "candidate_unmapped_rows": int(selected.canonical_doc_id.isna().sum()), "source_sha256": sha256(path)}
        views.append(selected)
    pd.concat(views, ignore_index=True).to_csv(output/"candidate-interactions.csv", index=False)
    write_json(output/"interaction-id-map.json", interaction_aliases)
    attempts = []
    batch_attempts = [read(p) for p in (ROOT/"batches").glob("*/*.json")]
    for identity in canonical:
        relevant = [{"source": a["source"], "error": a.get("attempt_error"),
                     "request_statuses": [r["status"] for r in a.get("requests", [])]}
                    for a in batch_attempts if identity in a.get("requested_ids", [])]
        attempts.append({"doc_id": identity, "queried_batch_attempts": relevant,
                         "official_not_queried_after_source_stop": not any(a["source"] == "arxiv" for a in relevant),
                         "final_source": collected.get(identity, {}).get("source_kind"),
                         "final_status": "acquired" if identity in collected else "not_acquired"})
    write_json(output/"fetch-attempts.json", attempts)
    summary = {"catalog_items": 2048, "coverage_counts": counts,
        "coverage_rates": {k: v/2048 for k, v in counts.items()}, "failure_items": len(failures),
        "source_counts": {kind: sum(r.get("source_kind") == kind for r in metadata) for kind in sorted({r.get("source_kind", "not_acquired") for r in metadata})},
        "identity": {"unique_original": len(set(original)), "unique_canonical": len(set(canonical)),
                     "collapsed_ids": 0, "mapping_complete": len(aliases) == 2048, "interactions": joins},
        "date_meaning": "first arXiv submission timestamp, not journal publication date",
        "historical_limit": "Current/snapshot text is for discovery only; not proven available at stage9 training cutoff",
        "unchanged_candidate_recall_ceiling": "Candidate set unchanged; metadata enrichment does not fix 5.21% future-like coverage",
        "local_user_rows": "candidate-interactions.csv remains local under source feedback license",
        "original_catalog_sha256": sha256(CATALOG)}
    write_json(output/"audit.json", summary)
    write_json(Path("reports/stage10/coverage.json"), summary)
    return summary


if __name__ == "__main__":
    print(json.dumps(build(), indent=2), flush=True)
