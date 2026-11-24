"""Read-only public snapshot probe; no arXiv requests during its cooldown."""
import json
import argparse
from pathlib import Path
import requests
from gsearch.metadata_fetch import MIRROR_REVISION


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-only", action="store_true")
    args = parser.parse_args()
    path = Path(".cache/stage10/mirror")
    path.mkdir(parents=True, exist_ok=True)
    repo = "secemp9/arxiv-complete"
    if args.manifest_only and (path/"repo.json").exists() and all((path/n).exists() for n in ("README.md", "LICENSE")):
        if json.loads((path/"repo.json").read_text())["sha"] == MIRROR_REVISION:
            print("Pinned snapshot manifest/license already cached", flush=True)
            return
    response = requests.get("https://huggingface.co/api/datasets/"+repo+"/revision/"+MIRROR_REVISION, timeout=(10, 45))
    response.raise_for_status()
    metadata = response.json()
    (path/"repo.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    revision = metadata["sha"]
    if revision != MIRROR_REVISION:
        raise ValueError("Unexpected snapshot revision")
    for name in ("README.md", "LICENSE"):
        r = requests.get(f"https://huggingface.co/datasets/{repo}/resolve/{revision}/{name}", timeout=(10, 45))
        r.raise_for_status()
        (path/name).write_bytes(r.content)
    if args.manifest_only:
        print(json.dumps({"repo_revision": revision, "manifest_only": True}), flush=True)
        return
    params = {"dataset": repo, "config": "metadata", "split": "train",
              "where": '"paper_id"=\'1105.1749\'', "length": 1}
    r = requests.get("https://datasets-server.huggingface.co/filter", params=params, timeout=(10, 60))
    (path/"probe.json").write_bytes(r.content)
    (path/"probe-headers.json").write_text(json.dumps(dict(r.headers), indent=2), encoding="utf-8")
    print(json.dumps({"repo_revision": revision, "status": r.status_code, "bytes": len(r.content),
                      "response_keys": list(r.json()) if r.status_code == 200 else r.text[:200]}), flush=True)


if __name__ == "__main__":
    main()
