"""Attach the enriched source-backed catalog to existing recommendation/Agent tools."""
import argparse
import json
from pathlib import Path

from .data import write_json
from .discovery import DiscoverySession
from .enrich_catalog import source_text_matches
from .paper_identity import arxiv_identity
from .paper_recommendation import load_recommender
from .retrieval import Corpus


class CatalogDiscoverySession(DiscoverySession):
    def _decorate(self, hits: list[dict]) -> list[dict]:
        rows = super()._decorate(hits)
        for row in rows:
            doc = self.corpus.by_id.get(row["doc_id"])
            if doc:
                metadata = doc["metadata"]
                row.update({"title": metadata["title"], "published_at": metadata["published_at"],
                            "source_url": metadata["source_url"], "source_kind": metadata["source_kind"],
                            "paper_key": metadata["paper_key"]})
            if self.method == "popular":
                row["reason"] = {"kind": "training_popularity", "positive_count": self.recommender.popularity[row["doc_id"]]}
        return rows

    def read(self, doc_id: str) -> dict:
        def operation() -> dict:
            identity, requested_version = arxiv_identity(doc_id)
            if identity not in self.retrieved:
                raise ValueError("Retrieve this canonical paper before reading any alias/version URL")
            if identity not in self.corpus.by_id:
                raise ValueError("Source abstract not acquired; no fabricated fallback")
            metadata = self.corpus.by_id[identity]["metadata"]
            if requested_version is not None and metadata.get("version") != requested_version:
                raise ValueError("Requested version text not acquired; do not substitute snapshot/latest text")
            if not metadata["coverage"]["citable"] or not source_text_matches(metadata):
                raise ValueError("Source response not validated")
            return {"doc_id": identity, "paper_key": metadata["paper_key"], "title": metadata["title"],
                    "abstract": metadata["abstract"], "published_at": metadata["published_at"],
                    "updated_at": metadata["updated_at"], "source_url": metadata["source_url"], "version": metadata.get("version"),
                    "source_kind": metadata["source_kind"], "metadata_license": metadata["metadata_license"],
                    "provenance": metadata["provenance"], "source_verified": True,
                    "semantic_stance_verified": False, "citation_unit": "original abstract, not full paper"}
        return self._call("read_paper", operation)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True)
    parser.add_argument("--query")
    parser.add_argument("--agent-task")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or not args.output.resolve().is_relative_to(Path("data").resolve()):
        raise ValueError("Use a new local-only data/ output path")
    session = CatalogDiscoverySession(load_recommender(), Corpus(Path("data/stage10-catalog/documents.json")), args.user)
    if args.agent_task:
        import torch
        from .local_model import LocalToolModel
        from .recommendation_agent import run
        torch.set_num_threads(4)
        model = LocalToolModel(model_id=".cache/models/Qwen2.5-1.5B-Instruct",
            device_map="cuda" if torch.cuda.is_available() else "cpu",
            torch_dtype="bfloat16" if torch.cuda.is_available() else "float32",
            model_kwargs={"local_files_only": True}, max_new_tokens=256, do_sample=False)
        result = run(session, args.agent_task, model)
    else:
        result = session.search(args.query) if args.query else session.recommend()
        if result.get("papers"):
            session.read(result["papers"][0]["doc_id"])
    write_json(args.output, {"result": result, "trace": session.trace,
               "catalog": "stage10 enriched metadata; not a retrained T5/NLI", "user_rows_local_only": True})
    print(json.dumps({"tool_calls": len(session.trace), "output": str(args.output),
                      "source_checked_selection": result.get("source_checked_selection")}), flush=True)


if __name__ == "__main__":
    main()
