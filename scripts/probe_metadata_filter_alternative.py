"""Check one independently hosted metadata-only mirror, without arXiv access."""
import json
from pathlib import Path
import requests


def main() -> None:
    root = Path(".cache/stage10/alternative")
    root.mkdir(parents=True, exist_ok=True)
    repo = "librarian-bots/arxiv-metadata-snapshot"
    r = requests.get("https://huggingface.co/api/datasets/"+repo, timeout=(10, 30))
    r.raise_for_status()
    metadata = r.json()
    (root/"repo.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    revision = metadata["sha"]
    r = requests.get(f"https://huggingface.co/datasets/{repo}/resolve/{revision}/README.md", timeout=(10, 30))
    r.raise_for_status()
    (root/"README.md").write_bytes(r.content)
    r = requests.get("https://datasets-server.huggingface.co/filter", params={"dataset":repo,"config":"default",
        "split":"train","where":'"id"=\'1105.1749\'',"length":1},timeout=(10,60))
    (root/"probe.json").write_bytes(r.content)
    print(json.dumps({"repo_revision":revision,"status":r.status_code,"bytes":len(r.content),
        "keys":list(r.json()) if r.status_code==200 else r.text[:180]}),flush=True)


if __name__ == "__main__":
    main()
