"""Use ZeroGR's extracted tree with HF's native T5 beam decoder."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path

import torch

from .retrieval import Corpus, GenerativeRetriever


ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "third_party/zerogr_prefix"


def upstream_tree_class() -> type:
    audit = json.loads((ROOT / "reports/stage7/upstream-audit.json").read_text(encoding="utf-8"))
    source = (VENDOR / "upstream_genir.py.txt").read_bytes()
    digest = hashlib.sha1(b"blob " + str(len(source)).encode() + b"\0" + source).hexdigest()
    if digest != audit["reuse"]["git_blob_sha"]:
        raise ValueError("Original ZeroGR source snapshot changed")
    original = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == "newTree")
    extracted = ast.parse((VENDOR / "tree.py").read_text(encoding="utf-8"))
    actual = next(n for n in extracted.body if isinstance(n, ast.ClassDef) and n.name == "newTree")
    if ast.dump(original) != ast.dump(actual):
        raise ValueError("Extracted upstream class differs from original")
    # Do not import genir.py: only the reviewed tree module with torch/tqdm imports.
    if any(not isinstance(n, (ast.Import, ast.ImportFrom, ast.ClassDef)) for n in extracted.body):
        raise ValueError("Unexpected standalone module statements")
    spec = importlib.util.spec_from_file_location("zerogr_standalone_tree", VENDOR / "tree.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.newTree


class PrefixIndex:
    def __init__(self, corpus: Corpus, tokenizer: object, compressed: bool):
        cls = upstream_tree_class()
        self.tree = cls(start_id=tokenizer.pad_token_id, end_id=tokenizer.eos_token_id, tokenizer=tokenizer)
        self.compressed = compressed
        docs = [{"id": d["doc_id"], "gist": d["code"]} for d in corpus.documents]
        if compressed:
            upstream_stats = self.tree.build(docs)
            if upstream_stats["docs"] != upstream_stats["save_docs"]:
                raise ValueError("Upstream compression lost documents")
        else:
            for doc in docs:
                self.tree.set(tokenizer.encode(doc["gist"], add_special_tokens=False) + [tokenizer.eos_token_id], doc["id"])
        self.aliases = []
        for path in self.tree.show():
            doc_ids = self.tree.get(path)
            if doc_ids is None or len(doc_ids) != 1 or path[-1] != tokenizer.eos_token_id:
                raise ValueError("Aliases must end in EOS and identify exactly one document")
            original = tokenizer.encode(corpus.by_id[doc_ids[0]]["code"], add_special_tokens=False)
            if path[:-1] != original[:len(path)-1] or (not compressed and path[:-1] != original):
                raise ValueError("Alias is not a prefix of the original tokenized ID")
            self.aliases.append({"doc_id": doc_ids[0], "token_ids": path,
                                 "alias": tokenizer.decode(path, skip_special_tokens=True),
                                 "original_tokens": len(original) + 1})
        if len(self.aliases) != len(corpus.documents) or {r["doc_id"] for r in self.aliases} != set(corpus.by_id):
            raise ValueError("Compression changed document coverage or identity")
        lengths = [len(r["token_ids"]) for r in self.aliases]
        self.maximum = max(lengths)
        self.stats = {"compressed": compressed, "documents": len(self.aliases),
                      "aliases": len(self.aliases), "actual_tree_nodes": len(self.tree.node_list),
                      "mean_tokens_including_eos": sum(lengths)/len(lengths),
                      "min_tokens": min(lengths), "max_tokens": max(lengths),
                      "one_alias_per_original_document": True}


class PrefixRetriever:
    def __init__(self, neural: GenerativeRetriever, index: PrefixIndex, beam: int):
        if type(beam) is not int or not 2 <= beam <= 100:
            raise ValueError("This adapter requires a beam decoder, 2<=beam<=100")
        self.neural, self.index, self.beam = neural, index, beam
        self.name = f"{'short' if index.compressed else 'full'}_b{beam}"
        self.receipts: list[dict] = []

    def search(self, query: str, k: int = 10) -> list[dict]:
        if not isinstance(query, str) or type(k) is not int or not 1 <= k <= self.beam <= 100:
            raise ValueError("Expected query and 1<=k<=beam<=100")
        tokenizer = self.neural.tokenizer
        inputs = tokenizer("search: " + query, return_tensors="pt", truncation=True,
                           max_length=self.neural.max_input).to(self.neural.device)
        with torch.inference_mode():
            generated = self.neural.model.generate(
                **inputs, num_beams=self.beam, num_return_sequences=k,
                max_new_tokens=self.index.maximum, do_sample=False, length_penalty=1.0,
                prefix_allowed_tokens_fn=self.index.tree, renormalize_logits=False,
                return_dict_in_generate=True, output_scores=True)
        result, lengths = [], []
        for sequence, score in zip(generated.sequences.cpu().tolist(), generated.sequences_scores.cpu().tolist()):
            tokens = sequence[1:]
            if tokenizer.eos_token_id not in tokens:
                raise ValueError("Decoded ID did not complete")
            tokens = tokens[:tokens.index(tokenizer.eos_token_id)+1]
            doc_ids = self.index.tree.get(tokens)
            if doc_ids is None or len(doc_ids) != 1:
                raise ValueError("Decoded alias is not uniquely mapped")
            doc_id = doc_ids[0]
            lengths.append(len(tokens))
            result.append({"doc_id": doc_id, "score": score,
                           "generated_code": tokenizer.decode(tokens, skip_special_tokens=True).strip(),
                           "generated_token_ids": tokens,
                           "original_full_code": self.neural.corpus.by_id[doc_id]["code"],
                           "title": self.neural.corpus.by_id[doc_id]["title"]})
        if len(result) != k or len({r["doc_id"] for r in result}) != k:
            raise ValueError("Decoded results are incomplete or duplicated")
        self.receipts.append({"query_sha256": hashlib.sha256(query.encode()).hexdigest(),
                              "encoder_input_tokens": int(inputs["attention_mask"].sum()),
                              "generation_steps": len(generated.scores),
                              "beam_decoder_slots": self.beam * len(generated.scores),
                              "returned_alias_tokens_including_eos": lengths})
        return result
