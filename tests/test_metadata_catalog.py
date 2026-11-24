"""Identity, real upstream feed parser, source integrity, and retrieval-to-citation identity."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

if importlib.util.find_spec("pandas") is None or importlib.util.find_spec("lxml") is None:
    raise unittest.SkipTest("Use original isolated runtime for metadata checks")

from gsearch.catalog_discovery import CatalogDiscoverySession
from gsearch.data import write_json
from gsearch.enrich_catalog import source_text_matches, valid_date
from gsearch.metadata_fetch import record_mirror, upstream
from gsearch.paper_identity import arxiv_identity, canonical_id
from gsearch.retrieval import Corpus


class MetadataTests(unittest.TestCase):
    def test_identity_aliases_versions_and_host_validation(self) -> None:
        aliases = ["2301.12345", "arXiv:2301.12345v3", "https://arxiv.org/abs/2301.12345v2",
                   "https://arxiv.org/pdf/2301.12345v1.pdf"]
        self.assertEqual({canonical_id(x) for x in aliases}, {"2301.12345"})
        self.assertEqual(arxiv_identity(aliases[1]), ("2301.12345", 3))
        self.assertEqual(arxiv_identity("https://arxiv.org/abs/hep-th/9901001v2"), ("hep-th/9901001", 2))
        for bad in ("https://evil.example/abs/2301.12345", "https://arxiv.org.evil/abs/2301.12345",
                    "2313.12345", "2301.12345v0", "../../2301.12345", "arxiv:garbage"):
            with self.assertRaises(ValueError):
                canonical_id(bad)

    def test_upstream_feed_parser_preserves_original_text(self) -> None:
        xml = b'''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
        <opensearch:totalResults>1</opensearch:totalResults><entry>
        <id>https://arxiv.org/abs/2301.12345v2</id><title>Original paper title</title>
        <summary>Exact original abstract.</summary><published>2023-01-04T10:00:00Z</published>
        <updated>2023-02-01T12:00:00Z</updated><author><name>Author One</name></author>
        <link href="https://arxiv.org/abs/2301.12345v2" rel="alternate" type="text/html"/>
        </entry></feed>'''
        feed = upstream()._feed.parse(xml)
        self.assertEqual(len(feed.results), 1)
        result = feed.results[0]
        self.assertEqual(result.summary, "Exact original abstract.")
        self.assertEqual(result.published.year, 2023)
        self.assertEqual(canonical_id(result.entry_id), "2301.12345")

    def test_snapshot_count_is_not_guessed_version(self) -> None:
        row = {"paper_id": "2301.12345", "n_versions": 4, "title": "T", "abstract": "A",
               "first_version_date": "2023-01-04", "latest_version_date": "2024-01-01"}
        record = record_mirror(row, {}, "commit")
        self.assertIsNone(record["version"])
        self.assertEqual(record["number_of_versions"], 4)
        self.assertTrue(valid_date(record["published_at"]))
        self.assertFalse(valid_date("not-a-date"))

    def test_read_alias_returns_original_and_rejects_text_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            body = json.dumps([{"paper_id": "2301.12345", "title": "Original title", "abstract": "Original abstract"}]).encode()
            (path/"raw.json").write_bytes(body)
            provenance = {"raw_path": str(path/"raw.json"), "raw_sha256": hashlib.sha256(body).hexdigest()}
            metadata = {"doc_id": "2301.12345", "paper_key": "arxiv:2301.12345", "title": "Original title",
                        "abstract": "Original abstract", "published_at": "2023-01-04", "updated_at": "2023-01-05",
                        "source_url": "https://arxiv.org/abs/2301.12345", "source_kind": "third_party_arxiv_oai_snapshot",
                        "metadata_license": "CC0-1.0", "provenance": provenance, "coverage": {"citable": True}}
            write_json(path/"docs.json", [{"doc_id": "2301.12345", "code": "2301.12345", "title": "Original title",
                                          "sentences": ["Original abstract"], "metadata": metadata}])
            class RecommenderStub:
                catalog = ["2301.12345"]
            session = CatalogDiscoverySession(RecommenderStub(), Corpus(path/"docs.json"), "contract")
            self.assertIn("error", session.read("arxiv:2301.12345v2"))
            session.retrieved.add("2301.12345")
            self.assertIn("error", session.read("https://arxiv.org/abs/2301.12345v2"))
            result = session.read("https://arxiv.org/abs/2301.12345")
            self.assertEqual(result["doc_id"], "2301.12345")
            self.assertEqual(result["abstract"], "Original abstract")
            self.assertTrue(result["source_verified"])
            session.corpus.by_id["2301.12345"]["metadata"]["abstract"] = "Made up text"
            session.max_calls = 5
            self.assertIn("error", session.read("2301.12345"))
            metadata["abstract"] = "Changed"
            self.assertFalse(source_text_matches(metadata))
            session.lexical.db.close()


if __name__ == "__main__":
    unittest.main()
