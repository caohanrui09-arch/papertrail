"""Download pinned official model files; verify all published LFS hashes."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import subprocess
from concurrent.futures import ThreadPoolExecutor


def download_weight(url: str, final: Path, size: int) -> None:
    chunks = final.parent / (final.name + ".chunks")
    chunks.mkdir(exist_ok=True)
    chunk_size = 16 * 1024 * 1024

    def fetch(start: int) -> Path:
        end = min(size, start + chunk_size) - 1
        path = chunks / str(start)
        if path.exists() and path.stat().st_size == end - start + 1:
            return path
        partial = path.with_suffix(".part")
        subprocess.run(["curl.exe", "--silent", "--show-error", "--fail", "--location", "--retry", "2", "--retry-all-errors",
                        "--connect-timeout", "30", "--max-time", "120", "--range", f"{start}-{end}",
                        "--output", str(partial), url + f"?download=true&part={start}"], check=True)
        if partial.stat().st_size != end - start + 1:
            raise ValueError("Range download returned unexpected length")
        partial.replace(path)
        print(f"{final.name}: chunk {start // chunk_size + 1} complete", flush=True)
        return path

    starts = list(range(0, size, chunk_size))
    with ThreadPoolExecutor(max_workers=8) as pool:
        parts = list(pool.map(fetch, starts))
    partial = final.with_suffix(final.suffix + ".part")
    with partial.open("wb") as output:
        for part in parts:
            with part.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
    partial.replace(final)

import requests


def download_model(repo: str, root: Path) -> dict:
    repo, _, requested_revision = repo.partition("@")
    target = root / repo.split("/")[-1]
    existing_source = target / "source.json"
    if not requested_revision and existing_source.exists():
        requested_revision = json.loads(existing_source.read_text(encoding="utf-8"))["revision"]
    revision_path = f"/revision/{requested_revision}" if requested_revision else ""
    response = requests.get(f"https://huggingface.co/api/models/{repo}{revision_path}?blobs=true", timeout=60)
    response.raise_for_status()
    metadata = response.json()
    revision = metadata["sha"]
    target.mkdir(parents=True, exist_ok=True)
    selected = {"config.json", "generation_config.json", "tokenizer.json", "tokenizer_config.json",
                "special_tokens_map.json", "spiece.model", "vocab.json", "merges.txt", "model.safetensors"}
    files = []
    for sibling in metadata["siblings"]:
        name = sibling["rfilename"]
        if name not in selected:
            continue
        final = target / name
        expected = sibling.get("lfs", {}).get("sha256")
        if not final.exists():
            url = f"https://huggingface.co/{repo}/resolve/{revision}/{name}"
            partial = final.with_suffix(final.suffix + ".part")
            print(f"Downloading {repo}/{name}", flush=True)
            if expected:
                download_weight(url, final, sibling["lfs"]["size"])
            else:
                body = requests.get(url, timeout=60)
                body.raise_for_status()
                partial.write_bytes(body.content)
                partial.replace(final)
        actual = hashlib.file_digest(final.open("rb"), "sha256").hexdigest()
        if expected and actual != expected:
            raise ValueError(f"Published hash mismatch: {final}")
        if expected:
            # Remove only exact numbered chunks created for this verified file.
            chunk_directory = target / (name + ".chunks")
            if chunk_directory.exists():
                for offset in range(0, sibling["lfs"]["size"], 16 * 1024 * 1024):
                    part = chunk_directory / str(offset)
                    if part.resolve().parent != chunk_directory.resolve():
                        raise ValueError("Unexpected chunk path")
                    part.unlink(missing_ok=True)
                if not any(chunk_directory.iterdir()):
                    chunk_directory.rmdir()
        files.append({"file": name, "sha256": actual, "published_sha256": expected,
                      "bytes": final.stat().st_size})
    if not (target / "model.safetensors").exists():
        raise ValueError("Expected safetensors weights missing")
    record = {"repo": repo, "revision": revision, "files": files, "downloaded_unix": time.time()}
    (target / "source.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(".cache/models"))
    parser.add_argument("--repo", action="append", required=True)
    args = parser.parse_args()
    for model_repo in args.repo:
        print(json.dumps(download_model(model_repo, args.root)), flush=True)
