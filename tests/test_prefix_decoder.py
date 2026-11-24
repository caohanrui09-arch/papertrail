import contextlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

import torch
from transformers import AutoTokenizer

from gsearch.prefix_decoder import PrefixIndex, PrefixRetriever, upstream_tree_class
from gsearch.retrieval import Corpus


class PrefixDecoderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tokenizer = AutoTokenizer.from_pretrained(".cache/models/t5-small", local_files_only=True)

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        path = Path(self.directory.name) / "documents.json"
        path.write_text(json.dumps([
            {"doc_id": "a", "code": "Oxygen for cells | 00000", "title": "First paper", "sentences": ["Original A."]},
            {"doc_id": "b", "code": "Water for cells | 00001", "title": "Second paper", "sentences": ["Original B."]},
            {"doc_id": "c", "code": "Water for plants | 00002", "title": "Third paper", "sentences": ["Original C."]}]), encoding="utf-8")
        self.corpus = Corpus(path)
        self.full = PrefixIndex(self.corpus, self.tokenizer, False)
        with contextlib.redirect_stderr(io.StringIO()):
            self.short = PrefixIndex(self.corpus, self.tokenizer, True)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_upstream_extraction_and_unique_compression(self) -> None:
        self.assertEqual(upstream_tree_class().__name__, "newTree")
        self.assertEqual({r["doc_id"] for r in self.short.aliases}, {"a", "b", "c"})
        self.assertLess(self.short.stats["mean_tokens_including_eos"], self.full.stats["mean_tokens_including_eos"])
        for row in self.short.aliases:
            self.assertEqual(self.short.tree.get(row["token_ids"]), [row["doc_id"]])

    def test_every_alias_is_a_legal_native_generation_path(self) -> None:
        for index in (self.full, self.short):
            for row in index.aliases:
                prefix = [self.tokenizer.pad_token_id]
                for token in row["token_ids"]:
                    self.assertIn(token, index.tree(0, torch.tensor(prefix)))
                    prefix.append(token)

    def contract_neural(self, sequences: list[list[int]]) -> object:
        class ContractOnlyModel:
            def generate(self, **kwargs: object) -> object:
                length = max(len(s) for s in sequences)
                padded = [s + [0]*(length-len(s)) for s in sequences]
                return SimpleNamespace(sequences=torch.tensor(padded),
                       sequences_scores=torch.tensor([-0.5]*len(sequences)), scores=[None]*(length-1))
        return SimpleNamespace(tokenizer=self.tokenizer, model=ContractOnlyModel(), device="cpu",
                               max_input=160, corpus=self.corpus)

    def test_raw_short_tokens_resolve_to_original_doc_and_title(self) -> None:
        aliases = self.short.aliases[:2]
        neural = self.contract_neural([[0] + r["token_ids"] for r in aliases])
        retriever = PrefixRetriever(neural, self.short, 2)
        hits = retriever.search("test claim", 2)
        self.assertEqual([h["doc_id"] for h in hits], [r["doc_id"] for r in aliases])
        for hit in hits:
            original = self.corpus.by_id[hit["doc_id"]]
            self.assertEqual(hit["title"], original["title"])
            self.assertEqual(hit["original_full_code"], original["code"])
        self.assertEqual(len(retriever.receipts), 1)

    def test_unmapped_or_duplicate_outputs_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            PrefixRetriever(self.contract_neural([[0, 9999, 1]]), self.short, 2).search("q", 1)
        seq = [0] + self.short.aliases[0]["token_ids"]
        with self.assertRaises(ValueError):
            PrefixRetriever(self.contract_neural([seq, seq]), self.short, 2).search("q", 2)

    def test_incomplete_output_and_non_beam_mode_are_rejected(self) -> None:
        seq = [0] + self.short.aliases[0]["token_ids"][:-1]
        with self.assertRaises(ValueError):
            PrefixRetriever(self.contract_neural([seq]), self.short, 2).search("q", 1)
        with self.assertRaises(ValueError):
            PrefixRetriever(self.contract_neural([[0, 1]]), self.short, 1)


if __name__ == "__main__":
    unittest.main()
