"""Pinned arxiv.py client plus bounded, cached public metadata acquisition."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import sys
import time

from filelock import FileLock
import requests

from .data import write_json
from .identifiers import sha256
from .paper_identity import arxiv_identity, canonical_id


ROOT = Path(".cache/stage10")
AUDIT = Path("reports/stage10")
CATALOG = Path("data/stage9-recommendation/catalog.json")
VENDOR = Path(__file__).resolve().parent.parent / "third_party/arxiv_py_upstream"
MIRROR = "secemp9/arxiv-complete"
MIRROR_REVISION = "cee894837962fede5612cccf2a4c7cacf49b4c3a"


def read(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def upstream() -> object:
    audit = read(AUDIT/"upstream-audit.json")
    for path, expected in audit["chosen"]["git_blobs"].items():
        b = (VENDOR/path).read_bytes()
        if hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest() != expected:
            raise ValueError("arxiv.py source changed")
    if str(VENDOR) not in sys.path:
        sys.path.insert(0, str(VENDOR))
    module = importlib.import_module("arxiv")
    if not Path(module.__file__).resolve().is_relative_to(VENDOR):
        raise ValueError("Unexpected arxiv module shadowing pinned source")
    return module


class RecordedSession(requests.Session):
    def __init__(self, label: str, interval: float):
        super().__init__()
        self.label, self.interval, self.receipts = label, interval, []
        self.mount("https://", requests.adapters.HTTPAdapter(pool_connections=1, pool_maxsize=1, pool_block=True))

    def get(self, url: str, **kwargs: object) -> requests.Response:
        state_path = ROOT/(self.label+"-pacing.json")
        if state_path.exists():
            remaining = self.interval-(time.time()-read(state_path)["last_request_epoch"])
            if remaining > 0:
                time.sleep(remaining)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(state_path, {"last_request_epoch": time.time()})
        kwargs.setdefault("timeout", (10, 45))
        headers = dict(kwargs.pop("headers", {}))
        headers["User-Agent"] = "generative-search-agent-metadata-audit/1.0 (local academic research)"
        response = super().get(url, headers=headers, **kwargs)
        digest = hashlib.sha256(response.content).hexdigest()
        raw = ROOT/"raw"/(digest+".body")
        raw.parent.mkdir(parents=True, exist_ok=True)
        if not raw.exists():
            raw.write_bytes(response.content)
        receipt = {"url": response.url, "status": response.status_code, "retrieved_at": utc(),
                   "content_type": response.headers.get("Content-Type"), "retry_after": response.headers.get("Retry-After"),
                   "raw_path": str(raw), "raw_sha256": digest, "bytes": len(response.content)}
        self.receipts.append(receipt)
        if response.status_code == 429:
            delay = max(300, int(response.headers.get("Retry-After", "300")) if response.headers.get("Retry-After", "300").isdigit() else 300)
            write_json(ROOT/"rate-limit.json", {"retry_not_before": datetime.fromtimestamp(time.time()+delay, timezone.utc).isoformat(),
                "reason": f"{self.label} HTTP429; stop, no alternate arxiv endpoint", "receipt": receipt})
        return response


def record_api(result: object, receipt: dict) -> dict:
    identity, version = arxiv_identity(result.entry_id)
    return {"doc_id": identity, "paper_key": "arxiv:"+identity, "version": version,
        "title": result.title, "abstract": result.summary, "published_at": result.published.isoformat(),
        "updated_at": result.updated.isoformat(), "source_url": f"https://arxiv.org/abs/{identity}"+(f"v{version}" if version else ""),
        "landing_url": f"https://arxiv.org/abs/{identity}", "authors": [a.name for a in result.authors],
        "source_kind": "official_arxiv_api", "metadata_license": "CC0-1.0", "provenance": receipt}


def record_mirror(row: dict, receipt: dict, revision: str) -> dict:
    identity = canonical_id(row["paper_id"])
    version = None  # a version count is not proof of the largest version number
    source = row.get("arxiv_abs_url") or "https://arxiv.org/abs/"+identity
    if canonical_id(source) != identity:
        raise ValueError("Snapshot source URL identity mismatch")
    return {"doc_id": identity, "paper_key": "arxiv:"+identity, "version": version,
        "number_of_versions": row.get("n_versions"),
        "title": row.get("title"), "abstract": row.get("abstract"), "published_at": row.get("first_version_date"),
        "updated_at": row.get("latest_version_date"), "source_url": f"https://arxiv.org/abs/{identity}"+(f"v{version}" if version else ""),
        "landing_url": "https://arxiv.org/abs/"+identity, "authors": row.get("authors"),
        "source_kind": "third_party_arxiv_oai_snapshot", "metadata_license": "CC0-1.0",
        "source_snapshot": {"repository": MIRROR, "repo_head_observed": revision, "harvest_date_declared": "2026-08-30",
            "filter_revision_pinned": False, "note": "filter service does not expose immutable revision; raw response preserved"},
        "provenance": receipt}


def fetch(source: str, max_batches: int | None = None) -> None:
    ids = read(CATALOG)
    canonical = [canonical_id(i) for i in ids]
    if len(canonical) != len(set(canonical)):
        raise ValueError("Catalog identities collapse; resolve before acquisition")
    if source == "arxiv" and (ROOT/"rate-limit.json").exists():
        if datetime.fromisoformat(read(ROOT/"rate-limit.json")["retry_not_before"]) > datetime.now(timezone.utc):
            print("Official API still cooling down; no request sent", flush=True)
            return
    cache = ROOT/"batches"/source
    cache.mkdir(parents=True, exist_ok=True)
    session = RecordedSession(source, 3.1 if source == "arxiv" else 1.0)
    client = None
    revision = None
    if source == "arxiv":
        package = upstream()
        client = package.Client(page_size=100, delay_seconds=3.1, num_retries=0)
        client._session = session  # transport-only timeout, pacing and raw-cache adapter
    else:
        revision = read(ROOT/"mirror/repo.json")["sha"]
        if revision != MIRROR_REVISION:
            raise ValueError("Snapshot revision differs from the selected immutable source")
    count = 0
    for start in range(0, len(canonical), 50 if source == "mirror" else 100):
        batch = canonical[start:start+(50 if source == "mirror" else 100)]
        key = hashlib.sha256("\n".join(batch).encode()).hexdigest()[:16]
        existing = sorted(cache.glob(key+"-*.json"))
        if existing and read(existing[-1]).get("complete"):
            continue
        if max_batches is not None and count >= max_batches:
            break
        count += 1
        first_receipt = len(session.receipts)
        records, error = [], None
        try:
            if source == "arxiv":
                result = list(client.results(package.Search(id_list=batch, max_results=len(batch))))
                if session.receipts[-1]["status"] != 200:
                    raise ValueError("Official API did not return200")
                records = [record_api(r, session.receipts[-1]) for r in result]
            else:
                # Exact OR predicates are the documented viewer filter syntax, not arbitrary SQL.
                where = " OR ".join('"paper_id"=\''+i+"'" for i in batch)
                response = session.get("https://datasets-server.huggingface.co/filter", params={
                    "dataset": MIRROR, "config": "metadata", "split": "train", "where": where, "length": 100})
                response.raise_for_status()
                payload = response.json()
                if payload.get("partial") or payload.get("num_rows_total", len(payload["rows"])) > 100:
                    raise ValueError("Partial or truncated snapshot response")
                records = [record_mirror(r["row"], session.receipts[-1], revision) for r in payload["rows"]]
            if any(r["doc_id"] not in batch for r in records) or len({r["doc_id"] for r in records}) != len(records):
                raise ValueError("Source returned unexpected/duplicate paper identities")
        except (requests.RequestException, ValueError, KeyError, AttributeError, TypeError) as exc:
            error = type(exc).__name__+": "+str(exc)
        except Exception as exc:
            # arxiv.py declares its own HTTP/feed exception hierarchy; preserve exact failure.
            error = type(exc).__name__+": "+str(exc)
        missing = sorted(set(batch)-{r["doc_id"] for r in records})
        receipt = {"source": source, "requested_ids": batch, "records": records,
            "missing": [{"doc_id": i, "reason": error or "no matching source entry returned; not proof of nonexistence"} for i in missing],
            "attempt_error": error, "complete": not missing and error is None, "retrieved_at": utc(),
            "requests": session.receipts[first_receipt:], "catalog_sha256": sha256(CATALOG)}
        write_json(cache/(key+f"-{len(existing)+1:03d}.json"), receipt)
        print(json.dumps({"source": source, "offset": start, "requested": len(batch), "received": len(records), "error": error}), flush=True)
        if error or any(r["status"] == 429 for r in receipt["requests"]):
            print("Stopping source after failure; receipts retained for bounded later retry", flush=True)
            break
    if source == "mirror":
        response = session.get("https://huggingface.co/api/datasets/"+MIRROR)
        response.raise_for_status()
        after = response.json()["sha"]
        write_json(ROOT/"mirror/revision-check.json", {"before": revision, "after": after, "unchanged": revision == after,
            "caveat": "HEAD stability does not prove filter index revision; raw payload hashes are authoritative for this acquisition"})
    session.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=("arxiv", "mirror"), default="arxiv")
    parser.add_argument("--max-batches", type=int)
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    with FileLock(str(ROOT/"acquisition.lock"), timeout=0):
        fetch(args.source, args.max_batches)


if __name__ == "__main__":
    main()
