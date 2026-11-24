"""Isolate optional PyTerrier dependencies while reading the existing CUDA runtime."""
from pathlib import Path
import sys
import venv


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    target = root / ".cache/stage6-env"
    shared = Path(sys.executable).resolve().parent.parent / "Lib/site-packages"
    if not (shared / "torch").exists():
        raise ValueError("Run this setup with the existing workspace CUDA venv interpreter")
    bridge = target / "Lib/site-packages/shared_workspace_runtime.pth"
    if target.exists():
        if not bridge.exists() or bridge.read_text(encoding="utf-8").strip() != str(shared):
            raise ValueError("Existing stage6 runtime has a different shared-library path")
    else:
        venv.EnvBuilder(with_pip=True).create(target)
        bridge.write_text(str(shared) + "\n", encoding="utf-8")
    print(target / "Scripts/python.exe")


if __name__ == "__main__":
    main()
