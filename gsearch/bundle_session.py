"""Claim-isolated tools and shared hard ceilings for all bundle policies."""
from dataclasses import asdict, dataclass, field
import json
import time
from typing import Callable


@dataclass(frozen=True)
class BundleBudget:
    searches: int = 4
    assessments: int = 4
    document_claim_pairs: int = 6
    max_steps: int = 12
    input_tokens: int = 24000
    output_tokens: int = 1600


@dataclass
class BundleSession:
    claims: dict[str, str]
    retrievers: dict[str, object]
    verifier: object
    budget: BundleBudget = field(default_factory=BundleBudget)
    searches: int = 0
    assessments: int = 0
    document_claim_pairs: int = 0
    generative_searches: int = 0
    retrieved: dict[str, set[str]] = field(default_factory=dict)
    assessed: dict[str, set[str]] = field(default_factory=dict)
    evidence: dict[str, dict[str, dict]] = field(default_factory=dict)
    trace: list[dict] = field(default_factory=list)
    checked: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if set(self.claims) != {"A", "B"} or not all(isinstance(c, str) and c.strip() for c in self.claims.values()):
            raise ValueError("Expected two nonempty original claims A and B")
        self.claims = dict(self.claims)
        for key in self.claims:
            self.retrieved[key], self.assessed[key], self.evidence[key] = set(), set(), {}

    def progress(self) -> dict:
        outputs = {}
        for key in self.claims:
            records = list(self.evidence[key].values())
            labels = {row["model_stance"] for row in records}
            outputs[key] = {"verdict": next(iter(labels)) if len(labels) == 1 else "INSUFFICIENT",
                            "citations": sorted(row["citation_id"] for row in records),
                            "checked": key in self.checked}
        return {"claims": outputs, "remaining": {"searches": self.budget.searches - self.searches,
                 "assessments": self.budget.assessments - self.assessments,
                 "document_claim_pairs": self.budget.document_claim_pairs - self.document_claim_pairs}}

    def _invoke(self, tool: str, arguments: dict, operation: Callable[[], dict]) -> dict:
        start = time.perf_counter()
        try:
            result = operation()
        except (ValueError, KeyError) as error:
            result = {"error": str(error), **self.progress()}
        self.trace.append({"tool": tool, "arguments": arguments, "result": result,
                           "seconds": time.perf_counter() - start})
        return result

    def search(self, claim_key: str, query: str, method: str, k: int = 3) -> dict:
        def operation() -> dict:
            if self.searches >= self.budget.searches:
                raise ValueError("Shared search budget exhausted")
            self.searches += 1
            if not isinstance(claim_key, str) or claim_key not in self.claims:
                raise ValueError("Unknown claim key; use A or B")
            if not isinstance(method, str) or method not in self.retrievers or type(k) is not int or not 1 <= k <= 10:
                raise ValueError("Unknown method or invalid k")
            if not isinstance(query, str) or (query != "" and not query.strip()) or len(query) > 2000:
                raise ValueError("Use an empty query for the original claim, or 1-2000 characters")
            effective_query = self.claims[claim_key] if query == "" else query
            hits = self.retrievers[method].search(effective_query, k)
            if method == "hybrid_checked":
                self.generative_searches += 1
            valid = [h for h in hits if h.get("doc_id") is not None]
            self.retrieved[claim_key].update(h["doc_id"] for h in valid)
            return {"claim_key": claim_key, "hits": valid, **self.progress()}
        return self._invoke("search_claim", {"claim_key": claim_key, "query": query, "method": method, "k": k}, operation)

    def assess(self, claim_key: str, doc_ids: list[str]) -> dict:
        def operation() -> dict:
            if self.assessments >= self.budget.assessments:
                raise ValueError("Shared assessment-call budget exhausted")
            self.assessments += 1
            if not isinstance(claim_key, str) or claim_key not in self.claims:
                raise ValueError("Unknown claim key; use A or B")
            if (not isinstance(doc_ids, list) or not 1 <= len(doc_ids) <= 3
                    or not all(isinstance(doc, str) for doc in doc_ids) or len(set(doc_ids)) != len(doc_ids)):
                raise ValueError("Provide 1-3 distinct retrieved document IDs")
            if any(doc not in self.retrieved[claim_key] for doc in doc_ids):
                raise ValueError("Each document must be retrieved FOR THIS CLAIM before assessment")
            if self.document_claim_pairs + len(doc_ids) > self.budget.document_claim_pairs:
                raise ValueError("Shared document-claim pair budget exhausted")
            # Charge every pair, including repeated/cached requests; never grant free retries.
            self.document_claim_pairs += len(doc_ids)
            result = self.verifier.assess(self.claims[claim_key], doc_ids)
            if any(row["doc_id"] not in doc_ids for row in result["evidence"]):
                raise ValueError("Verifier returned a document outside this claim's requested scope")
            self.assessed[claim_key].update(doc_ids)
            self.checked.add(claim_key)
            for doc in doc_ids:
                self.evidence[claim_key].pop(doc, None)
            for row in result["evidence"]:
                self.evidence[claim_key][row["doc_id"]] = {
                    "doc_id": row["doc_id"], "sentence_ids": row["sentence_ids"], "model_stance": row["stance"],
                    "citation_id": row["doc_id"] + ":" + ",".join(map(str, row["sentence_ids"])),
                    "quotes": row["quotes"], "source_verified": True, "semantic_stance_verified": False}
            return {"claim_key": claim_key, "new_evidence": list(self.evidence[claim_key].values()), **self.progress()}
        return self._invoke("assess_claim", {"claim_key": claim_key, "doc_ids": doc_ids}, operation)

    def finalize(self, answer: object) -> dict:
        if isinstance(answer, str):
            try:
                answer = json.loads(answer)
            except json.JSONDecodeError as error:
                raise ValueError("Return an object containing A and B") from error
        if not isinstance(answer, dict) or set(answer) != set(self.claims):
            raise ValueError("Final answer must contain BOTH A and B, no other keys")
        if self.checked != set(self.claims):
            raise ValueError("Both claims must be assessed before final_answer")
        expected = self.progress()["claims"]
        for key in self.claims:
            item = answer[key]
            if (not isinstance(item, dict) or set(item) != {"verdict", "citations"}
                    or not isinstance(item["citations"], list)
                    or not all(isinstance(c, str) for c in item["citations"])):
                raise ValueError(f"{key} must contain verdict and a list of citation ID strings")
            if item["verdict"] != expected[key]["verdict"] or sorted(set(item["citations"])) != expected[key]["citations"]:
                raise ValueError(f"Do not change {key}'s checked verdict or citations: {expected[key]}")
        return {key: {"verdict": expected[key]["verdict"], "citations": expected[key]["citations"],
                      "evidence": list(self.evidence[key].values()),
                      "assessment_kind": "independent_model_prediction_not_ground_truth"} for key in self.claims}

    def expected_answer(self) -> dict:
        return {key: {k: value for k, value in row.items() if k != "checked"}
                for key, row in self.progress()["claims"].items()}

    def usage(self) -> dict:
        return {"searches": self.searches, "assessments": self.assessments,
                "document_claim_pairs": self.document_claim_pairs, "generative_searches": self.generative_searches,
                "ceilings": asdict(self.budget)}
