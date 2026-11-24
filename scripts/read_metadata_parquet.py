"""Use Arrow/HfFileSystem to read only metadata columns from a pinned public file."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from gsearch.data import write_json
from gsearch.metadata_fetch import ROOT, MIRROR, MIRROR_REVISION, CATALOG, read, record_mirror


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    sys.path.insert(0, str((ROOT/"deps").resolve()))
    import pyarrow.parquet as pq
    import pyarrow.compute as pc
    import pyarrow as pa
    from huggingface_hub import HfFileSystem
    metadata = read(ROOT/"mirror/repo.json")
    revision = metadata["sha"]
    if revision != MIRROR_REVISION:
        raise ValueError("Snapshot revision differs from the selected immutable source")
    path = f"datasets/{MIRROR}@{revision}/metadata/train-00000-of-00001.parquet"
    fs = HfFileSystem(token=False)
    info = fs.info(path)
    write_json(ROOT/"mirror/parquet-source.json", {"repo_revision": revision, "file_info": info,
        "path": path, "license": "CC0 metadata only; no paper fulltext config fetched"})
    wanted = set(read(CATALOG))
    target = ROOT/"parquet-groups"
    target.mkdir(parents=True, exist_ok=True)
    with fs.open(path, "rb", block_size=64*1024*1024, cache_type="bytes") as handle:
        file = pq.ParquetFile(handle, pre_buffer=False)
        col_idx = file.schema_arrow.names.index("paper_id")
        stats = []
        for i in range(file.num_row_groups):
            stat = file.metadata.row_group(i).column(col_idx).statistics
            stats.append({"row_group": i, "rows": file.metadata.row_group(i).num_rows,
                "min_id": stat.min if stat else None, "max_id": stat.max if stat else None})
        write_json(ROOT/"mirror/parquet-layout.json", {"rows": file.metadata.num_rows,
            "columns": file.schema_arrow.names, "row_groups": stats})
        print(json.dumps({"rows": file.metadata.num_rows, "row_groups": file.num_row_groups, "source_size": info["size"]}), flush=True)
        if args.probe:
            return
        columns = ["paper_id", "title", "abstract", "first_version_date", "latest_version_date", "n_versions", "arxiv_abs_url", "authors"]
        def process(group: dict) -> None:
            index = group["row_group"]
            destination = target/f"group-{index:05d}.json"
            if destination.exists():
                return
            if group["min_id"] is not None and not any(group["min_id"] <= d <= group["max_id"] for d in wanted):
                return
            # Independent handles and bounded block caches avoid overlapping byte-cache re-downloads.
            with fs.open(path, "rb", block_size=4*1024*1024, cache_type="blockcache", cache_options={"maxblocks":16}) as source:
                local = pq.ParquetFile(source, pre_buffer=False)
                ids = local.read_row_group(index, columns=["paper_id"], use_threads=False)
                mask = pc.is_in(ids["paper_id"], value_set=pa.array(sorted(wanted), type=ids["paper_id"].type))
                matches = int(pc.sum(mask).as_py())
                table = local.read_row_group(index, columns=columns, use_threads=False).filter(mask) if matches else None
            # First read only the ID column; do not fetch abstract chunks for unmatched groups.
            if not matches:
                write_json(destination, {"records": [], "group": index, "source_revision": revision})
                print(json.dumps({"group": index, "matches": 0}), flush=True)
                return
            raw_rows = table.to_pylist()
            # JSON timestamps are exact Arrow values rendered as ISO strings, no inferred dates.
            raw_rows = [{k: v.isoformat() if hasattr(v, "isoformat") else v for k, v in r.items()} for r in raw_rows]
            body = json.dumps(raw_rows, ensure_ascii=False, sort_keys=True).encode()
            digest = hashlib.sha256(body).hexdigest()
            raw = ROOT/"raw"/(digest+".json")
            raw.write_bytes(body)
            receipt = {"url": f"https://huggingface.co/datasets/{MIRROR}/resolve/{revision}/metadata/train-00000-of-00001.parquet",
                "raw_path": str(raw), "raw_sha256": digest, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "row_group": index, "immutable_revision": revision,
                "note": "Exact selected metadata rows from immutable Parquet, not a live API response"}
            records = [record_mirror(r, receipt, revision) for r in raw_rows]
            for r in records:
                r["source_snapshot"]["filter_revision_pinned"] = True
                r["source_snapshot"]["note"] = "Pinned Parquet content, no filter service"
            write_json(destination, {"records": records, "group": index, "source_revision": revision})
            print(json.dumps({"group": index, "matches": matches, "saved": len(records)}), flush=True)

        if not 1 <= args.workers <= 4:
            raise ValueError("Use at most four public-mirror file readers; no arXiv API concurrency")
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(process, group): group["row_group"] for group in stats}
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    index = futures[future]
                    error = type(exc).__name__+": "+str(exc)
                    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
                    write_json(target/f"group-{index:05d}-{stamp}.error.json", {"records": [], "group":index,"error":error})
                    print(json.dumps({"group":index,"error":error}),flush=True)


if __name__ == "__main__":
    main()
