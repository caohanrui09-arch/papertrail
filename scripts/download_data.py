"""Download the official release used by this experiment, with a local snapshot hash."""
import hashlib
from pathlib import Path

import requests

SOURCE = "https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz"
# Observed in the official download on 2026-10-24, not a publisher-signed checksum.
SNAPSHOT_SHA256 = "11c621288d41ac144d29b13b0f8503b3820b7d6e8b1f6ff24dff335c196d76be"


def main() -> None:
    target = Path("data/raw/data.tar.gz")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        response = requests.get(SOURCE, timeout=120)
        response.raise_for_status()
        temporary = target.with_suffix(".part")
        temporary.write_bytes(response.content)
        actual = hashlib.file_digest(temporary.open("rb"), "sha256").hexdigest()
        if actual != SNAPSHOT_SHA256:
            raise ValueError("Official latest release changed; audit before accepting a new snapshot")
        temporary.replace(target)
    actual = hashlib.file_digest(target.open("rb"), "sha256").hexdigest()
    if actual != SNAPSHOT_SHA256:
        raise ValueError("Local release differs from the audited snapshot")
    print(f"Verified {target}: {actual}")


if __name__ == "__main__":
    main()
