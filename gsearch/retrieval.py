"""SQLite FTS5 is the BM25 implementation; HF generate owns neural beam search."""
from collections import defaultdict
import json
from pathlib import Path
import re
import sqlite3

from .data import fingerprint


class Corpus:
    def __init__(self, path: Path):
        self.documents = json.loads(path.read_text(encoding="utf-8"))
        self.by_id = {d["doc_id"]: d for d in self.documents}
        self.by_code = {d["code"]: d["doc_id"] for d in self.documents}
        self.fingerprint = fingerprint(self.documents)
        if not self.documents or len(self.by_id) != len(self.documents) or len(self.by_code) != len(self.documents):
            raise ValueError("Empty or ambiguous corpus")


class BM25:
    name = "sqlite_fts5_bm25"

    def __init__(self, corpus: Corpus):
        self.corpus = corpus
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.execute("CREATE VIRTUAL TABLE docs USING fts5(doc_id UNINDEXED, title, body, tokenize='porter unicode61')")
        self.db.executemany("INSERT INTO docs VALUES (?,?,?)",
                            [(d["doc_id"], d["title"], " ".join(d["sentences"])) for d in corpus.documents])

    def search(self, query: str, k: int = 10) -> list[dict]:
        if not isinstance(query, str) or not 1 <= k <= 100:
            raise ValueError("Expected text query and 1<=k<=100")
        # Tokenize and quote; do not pass user-provided FTS syntax to MATCH.
        words = list(dict.fromkeys(re.findall(r"\w+", query.casefold())))[:128]
        stop = {"a", "an", "the", "is", "are", "of", "to", "in", "and", "or", "that", "with", "for", "by"}
        expression = " OR ".join(f'"{w}"' for w in words if w not in stop)
        if not expression:
            return []
        rows = self.db.execute("SELECT doc_id, bm25(docs, 0, 2, 1) AS score FROM docs WHERE docs MATCH ? ORDER BY score, doc_id LIMIT ?",
                               (expression, k)).fetchall()
        return [{"doc_id": doc_id, "score": -score, "title": self.corpus.by_id[doc_id]["title"]}
                for doc_id, score in rows]


class DocumentTrie:
    """Encoder-decoder output: drop decoder_start, retain ID tokens and EOS."""
    def __init__(self, tokenizer: object, codes: list[str]):
        self.children: dict[tuple[int, ...], set[int]] = defaultdict(set)
        self.maximum = 0
        sequences = set()
        self.eos = tokenizer.eos_token_id
        for code in codes:
            sequence = tuple(tokenizer.encode(code, add_special_tokens=False)) + (self.eos,)
            if sequence in sequences:
                raise ValueError("Different codes tokenize to the same ID")
            sequences.add(sequence)
            self.maximum = max(self.maximum, len(sequence))
            for depth, token in enumerate(sequence):
                self.children[sequence[:depth]].add(token)

    def allowed(self, batch_id: int, output_ids: object) -> list[int]:
        prefix = tuple(output_ids.tolist()[1:])
        if self.eos in prefix:
            return [self.eos]
        tokens = self.children.get(prefix)
        if not tokens:
            raise ValueError(f"Illegal document prefix: {prefix}")
        return sorted(tokens)


class GenerativeRetriever:
    name = "t5_dsi"

    def __init__(self, corpus: Corpus, checkpoint: Path, beam: int = 10):
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        self.corpus = corpus
        self.beam = beam
        metadata = json.loads((checkpoint / "run.json").read_text(encoding="utf-8"))
        if metadata["corpus_fingerprint"] != corpus.fingerprint:
            raise ValueError("Checkpoint and corpus differ")
        self.max_input = metadata["max_input"]
        self.tokenizer = AutoTokenizer.from_pretrained(checkpoint, local_files_only=True)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = AutoModelForSeq2SeqLM.from_pretrained(checkpoint, local_files_only=True).to(self.device).eval()
        self.trie = DocumentTrie(self.tokenizer, list(corpus.by_code))

    def search(self, query: str, k: int = 10) -> list[dict]:
        import torch
        if not isinstance(query, str) or not 1 <= k <= 100 or self.beam < k:
            raise ValueError("Expected text query, 1<=k<=beam<=100")
        inputs = self.tokenizer("search: " + query, return_tensors="pt", truncation=True,
                                max_length=self.max_input).to(self.device)
        with torch.inference_mode():
            generated = self.model.generate(**inputs, num_beams=self.beam, num_return_sequences=k,
                                            max_new_tokens=self.trie.maximum, do_sample=False,
                                            prefix_allowed_tokens_fn=self.trie.allowed,
                                            return_dict_in_generate=True, output_scores=True)
        codes = self.tokenizer.batch_decode(generated.sequences, skip_special_tokens=True)
        result = []
        for code, score in zip(codes, generated.sequences_scores.tolist()):
            doc_id = self.corpus.by_code.get(code.strip())
            result.append({"doc_id": doc_id, "score": score, "generated_code": code,
                           "title": self.corpus.by_id[doc_id]["title"] if doc_id else None})
        return result


class Hybrid:
    name = "rrf_bm25_t5"

    def __init__(self, first: object, second: object):
        self.first, self.second = first, second

    def search(self, query: str, k: int = 10) -> list[dict]:
        scores: dict[str, float] = defaultdict(float)
        records = {}
        for retriever in (self.first, self.second):
            for rank, hit in enumerate(retriever.search(query, k), 1):
                if hit["doc_id"]:
                    scores[hit["doc_id"]] += 1 / (60 + rank)
                    records[hit["doc_id"]] = hit
        return [{**records[d], "score": scores[d]} for d in sorted(scores, key=lambda d: (-scores[d], d))[:k]]
