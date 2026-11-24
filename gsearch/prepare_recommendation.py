"""Time-based recommendation splits; transformed data stays in ignored local data/."""
import json
from pathlib import Path

import pandas as pd

from .data import write_json
from .identifiers import sha256
from scripts.download_scholar_inbox import FILES, ROOT as SOURCE, git_blob


OUTPUT = Path("data/stage9-recommendation")
CATALOG_LIMIT = 2048


def main() -> None:
    if OUTPUT.exists():
        raise ValueError("Refusing to overwrite recommendation preparation")
    for name, (size, blob) in FILES.items():
        b = (SOURCE / name).read_bytes()
        if len(b) != size or git_blob(b) != blob:
            raise ValueError("Original source changed")
    raw = pd.read_csv(SOURCE / "data/rated_papers.csv", dtype={"user_id": str, "arxiv_id": str})
    if not raw.rating.isin([-1, 1]).all() or raw.duplicated(["user_id", "arxiv_id"]).any():
        raise ValueError("Unexpected rating labels or duplicate pairs")
    timestamp = pd.to_datetime(raw.time, format="mixed", errors="coerce", utc=True)
    valid = raw[timestamp.notna()].copy()
    valid["time"] = timestamp[timestamp.notna()]
    times = valid.time.sort_values()
    cut1, cut2 = times.iloc[int(len(times)*0.8)], times.iloc[int(len(times)*0.9)]
    splits = {"train": valid[valid.time < cut1],
              "tuning": valid[(valid.time >= cut1) & (valid.time < cut2)],
              "dev": valid[valid.time >= cut2]}
    positive = splits["train"][splits["train"].rating == 1]
    counts = positive.arxiv_id.value_counts().to_dict()
    catalog = sorted(sorted(counts, key=lambda d: (-counts[d], d))[:CATALOG_LIMIT])
    OUTPUT.mkdir(parents=True)
    # Keep ALL heldout likes in the denominator, including untrained/out-of-catalog papers.
    for name, frame in splits.items():
        frame.sort_values(["time", "user_id", "arxiv_id"]).to_csv(OUTPUT / f"{name}.csv", index=False)
    write_json(OUTPUT / "catalog.json", catalog)
    annotations = pd.read_csv(SOURCE / "data/abstract_sentences.csv", dtype={"arxiv_id": str})
    if (annotations.groupby("arxiv_id")["abstract"].nunique() > 1).any():
        raise ValueError("Conflicting original abstracts require explicit resolution")
    unique = annotations.drop_duplicates("arxiv_id")
    documents = [{"doc_id": r.arxiv_id, "code": r.arxiv_id, "title": "arXiv:"+r.arxiv_id,
                  "sentences": [r.abstract], "title_is_identifier_only": True,
                  "source": "released original abstract; not generated evidence"}
                 for r in unique.itertuples() if r.arxiv_id in set(catalog)]
    write_json(OUTPUT / "documents.json", sorted(documents, key=lambda r: r["doc_id"]))
    report = {"source_rows": len(raw), "users": raw.user_id.nunique(), "papers": raw.arxiv_id.nunique(),
              "ratings": {str(k): int(v) for k, v in raw.rating.value_counts().items()},
              "missing_or_invalid_time_rows_excluded": int(timestamp.isna().sum()),
              "cutoffs": {"train_exclusive": cut1.isoformat(), "tuning_exclusive": cut2.isoformat()},
              "timestamp_note": "Source timezone unspecified; parsed UTC only for consistent ordering",
              "catalog_limit": CATALOG_LIMIT, "catalog_items": len(catalog),
              "catalog_rule": "training positive frequency descending, arxiv ID tie-break, no holdout labels",
              "available_original_abstracts_in_catalog": len(documents), "all_original_abstracts": len(unique),
              "splits": {name: {"rows": len(frame), "users": frame.user_id.nunique(),
                  "likes": int((frame.rating == 1).sum()), "dislikes": int((frame.rating == -1).sum()),
                  "likes_inside_catalog": int(((frame.rating == 1)&frame.arxiv_id.isin(catalog)).sum())}
                  for name, frame in splits.items()},
              "source_manifest_sha256": sha256(SOURCE / "source.json"),
              "local_only": "CC BY-NC-ND4.0: derived per-user data/predictions not redistributed"}
    write_json(OUTPUT / "audit.json", report)
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
