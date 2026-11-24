"""Deterministic controls and an LLM policy share the exact same tool service."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time

from .bundle_session import BundleSession


def classifier_work(verifier: object) -> dict:
    result = {}
    for name in ("relevance", "rationale", "nli"):
        model = getattr(verifier, name, None)
        if model is not None:
            result[name] = {key: getattr(model, key, 0)
                            for key in ("pairs_processed", "forward_batches", "padded_input_tokens")}
    return result


def run_fixed(session: BundleSession) -> dict:
    """Strong single-pass control: spend three assessed documents on EACH claim."""
    for key, claim in session.claims.items():
        hits = session.search(key, claim, "hybrid_checked", 3).get("hits", [])
        if hits:
            session.assess(key, [h["doc_id"] for h in hits[:3]])
    return session.finalize(session.expected_answer())


def run_rule(session: BundleSession) -> dict:
    """Simple uncertainty rule, no learned planner and no gold access."""
    for key, claim in session.claims.items():
        hits = session.search(key, claim, "hybrid_checked", 2).get("hits", [])
        if hits:
            session.assess(key, [h["doc_id"] for h in hits[:2]])
    unresolved = [key for key, result in session.progress()["claims"].items() if result["verdict"] == "INSUFFICIENT"]
    for key in unresolved:
        remaining = session.budget.document_claim_pairs - session.document_claim_pairs
        if not remaining:
            break
        # Split the remaining capacity when both claims are unresolved; otherwise focus it.
        allocation = 1 if len(unresolved) == 2 else min(2, remaining)
        hits = session.search(key, session.claims[key], "bm25", 10).get("hits", [])
        fresh = [h["doc_id"] for h in hits if h["doc_id"] not in session.assessed[key]][:allocation]
        if fresh:
            session.assess(key, fresh)
    return session.finalize(session.expected_answer())


def build_bundle_tools(session: BundleSession) -> list:
    from smolagents import tool

    @tool
    def search_claim(claim_key: str, method: str, k: int, query: str = "") -> str:
        """Search for one immutable claim. Results are available only to that claim.

        Args:
            claim_key: A or B, the original claim to search for.
            query: Leave empty to search the immutable original claim without copying/escaping it; optional rewritten query up to 2000 characters.
            method: hybrid_checked for generative plus BM25 reranking, or bm25.
            k: Number of results, integer from 1 to 10.
        """
        return json.dumps(session.search(claim_key, query, method, k), ensure_ascii=False)

    @tool
    def assess_claim(claim_key: str, doc_ids: list[str]) -> str:
        """Assess documents against the ORIGINAL claim; record accepted source citations.

        Args:
            claim_key: A or B. Evidence is never shared across claims.
            doc_ids: One to three distinct IDs retrieved for this claim. Every pair costs budget, including repeats.
        """
        return json.dumps(session.assess(claim_key, doc_ids), ensure_ascii=False)

    return [search_claim, assess_claim]


def run_llm(session: BundleSession, model: object) -> tuple[dict | None, dict]:
    from smolagents import ToolCallingAgent
    model.reset_budget(session.budget)

    def final_check(answer: object, agent: object) -> bool:
        session.finalize(answer)
        return True

    agent = ToolCallingAgent(model=model, tools=build_bundle_tools(session), max_steps=session.budget.max_steps,
                             max_tool_threads=1, final_answer_checks=[final_check], verbosity_level=0)
    agent.prompt_templates["system_prompt"] = (Path(__file__).parent / "prompts/bundle.txt").read_text(encoding="utf-8")
    answer = None
    error = None
    try:
        answer = agent.run(json.dumps({"task": "Check both independent claims separately.", "claims": session.claims},
                                      ensure_ascii=False))
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    steps = [step.dict() for step in agent.memory.steps]
    exhausted = any(step.get("error", {}).get("type") == "AgentMaxStepsError" for step in steps if step.get("error"))
    result = None
    if error is None and not exhausted:
        try:
            result = session.finalize(answer)
        except ValueError as exc:
            error = str(exc)
    return result, {"llm_usage": {key: value for key, value in asdict(model.meter).items() if key != "budget"},
                    "model": model.model_id, "prompt_sha256": hashlib.sha256(agent.system_prompt.encode()).hexdigest(),
                    "steps": steps, "error": error, "framework_steps_exhausted": exhausted,
                    "unverified_final_text": str(answer)}


def run_policy(policy: str, session: BundleSession, model: object | None = None) -> dict:
    session.verifier.cache.clear()
    before = classifier_work(session.verifier)
    start = time.perf_counter()
    metadata = {}
    error = None
    result = None
    try:
        if policy == "single_pass":
            result = run_fixed(session)
        elif policy == "rule_adaptive":
            result = run_rule(session)
        elif policy == "llm_agent":
            result, metadata = run_llm(session, model)
        else:
            raise ValueError("Unknown bundle policy")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    after = classifier_work(session.verifier)
    work = {name: {key: value - before[name][key] for key, value in counters.items()}
            for name, counters in after.items()}
    return {"policy": policy, "completed_protocol": result is not None, "checked_results": result,
            "diagnostic_progress": session.progress(), "seconds": time.perf_counter() - start,
            "tool_usage": session.usage(), "classifier_work": work, "tool_trace": session.trace,
            "error": error, "llm_metadata": metadata,
            "assessment_kind": "independent_model_predictions_not_ground_truth"}
