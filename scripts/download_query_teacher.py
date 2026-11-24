"""Pinned tensor-only conversion of the original doc2query teacher checkpoint."""
import json
from pathlib import Path

import requests

from gsearch.identifiers import sha256
from scripts.download_assets import download_weight


ROOT = Path(".cache/models/msmarco-t5-small-v1")
REPO = "doc2query/msmarco-t5-small-v1"
REVISION = "eb04306040c87ff35caa4c87078dfd94a6b7b64e"


def main() -> None:
    source_path = ROOT / "source.json"
    if source_path.exists():
        cached = json.loads(source_path.read_text(encoding="utf-8"))
        if cached["repo"] != REPO or cached["revision"] != REVISION:
            raise ValueError("Cached teacher belongs to another revision")
        if sha256(ROOT / "model.safetensors") != cached["converted_weights_sha256"]:
            raise ValueError("Cached converted weights changed")
        for entry in cached["files"]:
            # save_pretrained rewrites only the model config during conversion.
            if entry["file"] != "config.json" and sha256(ROOT / entry["file"]) != entry["sha256"]:
                raise ValueError(f"Cached original file changed: {entry['file']}")
        manifest_path = Path("data/stage5-queries/manifest.json")
        if manifest_path.exists():
            from gsearch.query_augmentation import teacher_state
            if teacher_state() != json.loads(manifest_path.read_text(encoding="utf-8"))["teacher"]:
                raise ValueError("Cached teacher differs from recorded generation assets")
        print("Cached pinned teacher verified; original conversion preserved", flush=True)
        return
    metadata_path = Path("reports/stage5/teacher-api.json")
    if not metadata_path.exists():
        response = requests.get(f"https://huggingface.co/api/models/{REPO}/revision/{REVISION}?blobs=true", timeout=60)
        response.raise_for_status()
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(json.dumps(response.json(), indent=2), encoding="utf-8")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata["sha"] != REVISION:
        raise ValueError("Unexpected teacher revision")
    selected = {"config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json",
                "spiece.model", "pytorch_model.bin", "README.md"}
    ROOT.mkdir(parents=True, exist_ok=True)
    files = []
    for sibling in metadata["siblings"]:
        name = sibling["rfilename"]
        if name not in selected:
            continue
        final = ROOT / name
        url = f"https://huggingface.co/{REPO}/resolve/{REVISION}/{name}"
        if not final.exists():
            if name == "pytorch_model.bin":
                download_weight(url, final, sibling["size"])
            else:
                response = requests.get(url, timeout=60)
                response.raise_for_status()
                final.write_bytes(response.content)
        actual = sha256(final)
        expected = sibling.get("lfs", {}).get("sha256")
        if final.stat().st_size != sibling["size"] or expected and actual != expected:
            raise ValueError(f"Published file check failed: {name}")
        files.append({"file": name, "sha256": actual, "published_sha256": expected,
                      "bytes": final.stat().st_size})
    # Do not execute downloaded Python or deserialize optimizer/training arguments.
    import torch
    from transformers import AutoConfig, AutoModelForSeq2SeqLM
    config = AutoConfig.from_pretrained(ROOT, local_files_only=True, trust_remote_code=False)
    if config.model_type != "t5":
        raise ValueError("Expected built-in T5 architecture")
    tensor_state = torch.load(ROOT / "pytorch_model.bin", map_location="cpu", weights_only=True)
    if not isinstance(tensor_state, dict) or not all(isinstance(v, torch.Tensor) for v in tensor_state.values()):
        raise ValueError("Expected tensor-only state dictionary")
    torch.manual_seed(42)
    model = AutoModelForSeq2SeqLM.from_config(config, trust_remote_code=False)
    model.load_state_dict(tensor_state, strict=True)
    model.save_pretrained(ROOT, safe_serialization=True)
    record = {"repo": REPO, "revision": REVISION, "files": files,
              "license": "Apache-2.0 per original model card",
              "conversion": "torch.load(weights_only=True), strict built-in T5 load, save_pretrained safetensors",
              "converted_weights_sha256": sha256(ROOT / "model.safetensors")}
    (ROOT / "source.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps(record), flush=True)


if __name__ == "__main__":
    main()
