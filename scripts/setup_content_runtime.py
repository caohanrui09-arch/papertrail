"""Project-local binary dependencies for the content baseline; shared env untouched."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import requests


ROOT = Path(".cache/stage11")
LOCK = Path("reports/stage11/runtime-lock.json")


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    if LOCK.exists():
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
    else:
        lock = {"scope": "project-local target; no numpy/scipy/CUDA upgrades", "packages": {}}
        for package in ("scikit-learn", "joblib", "threadpoolctl"):
            r = requests.get(f"https://pypi.org/pypi/{package}/json", timeout=(10, 45))
            r.raise_for_status()
            info = r.json()
            suffix = "cp312-cp312-win_amd64.whl" if package == "scikit-learn" else "py3-none-any.whl"
            choices = [f for f in info["urls"] if f["filename"].endswith(suffix)]
            if len(choices) != 1:
                raise ValueError("Expected one compatible binary wheel for "+package)
            lock["packages"][package] = {"version": info["info"]["version"], "wheel": choices[0],
                "license": info["info"].get("license_expression") or info["info"].get("license"),
                "requires_dist": info["info"].get("requires_dist")}
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        LOCK.write_text(json.dumps(lock, indent=2), encoding="utf-8")
    # Current joblib publishes cloudpickle as a runtime dependency; keep it isolated too.
    if "cloudpickle" not in lock["packages"]:
        r = requests.get("https://pypi.org/pypi/cloudpickle/json", timeout=(10, 45))
        r.raise_for_status()
        info = r.json()
        choices = [f for f in info["urls"] if f["filename"].endswith("py3-none-any.whl")]
        if len(choices) != 1:
            raise ValueError("Expected one cloudpickle wheel")
        lock["packages"]["cloudpickle"] = {"version":info["info"]["version"],"wheel":choices[0],
            "license":info["info"].get("license_expression") or info["info"].get("license"),
            "requires_dist":info["info"].get("requires_dist")}
        LOCK.write_text(json.dumps(lock,indent=2),encoding="utf-8")
    files = []
    for name, record in lock["packages"].items():
        wheel = record["wheel"]
        path = ROOT/"wheels"/wheel["filename"]
        if not path.exists():
            r = requests.get(wheel["url"], timeout=(10, 120))
            r.raise_for_status()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(r.content)
        if hashlib.sha256(path.read_bytes()).hexdigest() != wheel["digests"]["sha256"]:
            raise ValueError("Wheel digest mismatch: "+name)
        files.append(str(path))
    subprocess.run([sys.executable,"-m","pip","install","--no-index","--no-deps","--upgrade","--target",str(ROOT/"deps"),*files],check=True)
    print(json.dumps({name:r["version"] for name,r in lock["packages"].items()}),flush=True)


if __name__ == "__main__":
    main()
