"""Real local T5 tokenization: title collision and decoding boundary checks."""
import copy
from pathlib import Path
import unittest

import torch
from transformers import AutoTokenizer

from gsearch.benchmark_identifiers import assert_same
from gsearch.identifiers import title_documents
from gsearch.retrieval import DocumentTrie


class IdentifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        path = Path(".cache/models/t5-small")
        if not path.exists():
            raise unittest.SkipTest("Offline T5 tokenizer not prepared")
        cls.tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)

    def test_shared_and_unknown_titles_still_decode_to_distinct_documents(self) -> None:
        docs = [{"doc_id": str(i), "code": f"{i:05d}", "title": title, "sentences": []}
                for i, title in enumerate(["Cells in oxygen " * 8, "Cells in oxygen " * 8,
                                           "β-catenin's \"effect\"", "🧬", ""])]
        original = copy.deepcopy(docs)
        converted = title_documents(docs, self.tokenizer)
        self.assertEqual(docs, original)
        self.assertEqual(len({d["code"] for d in converted}), len(docs))
        for old, new in zip(docs, converted):
            self.assertTrue(new["code"].endswith(" | " + old["code"]))
            self.assertEqual(self.tokenizer.decode(self.tokenizer.encode(new["code"]),
                                                   skip_special_tokens=True).strip(), new["code"])

    def test_every_complete_textual_id_is_a_legal_trie_path(self) -> None:
        docs = title_documents([{"doc_id": "a", "code": "00001", "title": "Cells", "sentences": []},
                                {"doc_id": "b", "code": "00002", "title": "Cells grow", "sentences": []}],
                               self.tokenizer)
        trie = DocumentTrie(self.tokenizer, [d["code"] for d in docs])
        for doc in docs:
            prefix = [self.tokenizer.pad_token_id]
            for token in self.tokenizer.encode(doc["code"]):
                self.assertIn(token, trie.allowed(0, torch.tensor(prefix)))
                prefix.append(token)

    def test_duplicate_mapping_is_rejected(self) -> None:
        doc = {"doc_id": "a", "code": "00001", "title": "Cells", "sentences": []}
        with self.assertRaises(ValueError):
            title_documents([doc, doc], self.tokenizer)
        with self.assertRaises(ValueError):
            title_documents([doc], self.tokenizer, True)

    def test_frozen_manifest_drift_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "drift"):
            assert_same({"weights": "different"}, {"weights": "frozen"})


if __name__ == "__main__":
    unittest.main()
