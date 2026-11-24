"""Download pinned public research data; verify exact original Git blobs."""
import hashlib
from pathlib import Path

import requests

from gsearch.data import write_json


REF = "92b0fac32110b1243081476f69607cf51aa71ad4"
ROOT = Path(".cache/scholar-inbox-source")
FILES = {"data/rated_papers.csv": (35524300, "40b76cf7f6c0db5d7cbd865021ba9a177679a86e"),
         "data/abstract_sentences.csv": (3070828, "53a0c1112c87e27683ee59dfae0528e4da1eb3d7"),
         "LICENSE": (17529, "dc1adf98654156baeb94d2e055c224a847e5820d"),
         "README.md": (1098, "8ada852b7a64144801b9128abd233102b6ef8ead")}


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def main() -> None:
    manifest = {}
    for name, (size, expected) in FILES.items():
        path = ROOT / name
        url = f"https://raw.githubusercontent.com/avg-dev/scholar_inbox_datasets/{REF}/{name}"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            response = requests.get(url, timeout=(15, 120))
            response.raise_for_status()
            data = response.content
            if len(data) != size or git_blob(data) != expected:
                raise ValueError(f"Public source integrity mismatch: {name}")
            path.write_bytes(data)
        data = path.read_bytes()
        if len(data) != size or git_blob(data) != expected:
            raise ValueError(f"Source cache integrity mismatch: {name}")
        manifest[name] = {"url": url, "git_blob_sha": expected, "bytes": size,
                          "sha256": hashlib.sha256(data).hexdigest()}
        print(f"Verified original {name}: {size} bytes", flush=True)
    write_json(ROOT / "source.json", {"revision": REF, "license": "CC BY-NC-ND 4.0",
            "scope": "local noncommercial research; no adapted dataset redistribution", "files": manifest})


if __name__ == "__main__":
    main()
