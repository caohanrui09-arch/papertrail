"""Install a single pinned Arrow wheel into a project-local target, never shared env."""
import json
from pathlib import Path
import subprocess
import sys
import requests


def main() -> None:
    root = Path(".cache/stage10")
    r = requests.get("https://pypi.org/pypi/pyarrow/26.0.0/json", timeout=(10, 30))
    r.raise_for_status()
    info = r.json()
    version = info["info"]["version"]
    if version != "26.0.0":
        raise ValueError("Unexpected metadata reader version")
    selected = [f for f in info["urls"] if f["filename"].endswith("cp312-cp312-win_amd64.whl")]
    if len(selected) != 1:
        raise ValueError("Expected exactly one Windows CPython3.12 binary wheel")
    receipt = {"package": "pyarrow", "version": version, "license": info["info"].get("license_expression") or info["info"].get("license"),
               "wheel": selected[0], "shared_environment_modified": False}
    root.mkdir(parents=True, exist_ok=True)
    (root/"pyarrow-install-receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps", "--only-binary=:all:",
                    "--target", str(root/"deps"), "pyarrow=="+version], check=True)
    print("Project-local binary reader installed: pyarrow=="+version, flush=True)


if __name__ == "__main__":
    main()
