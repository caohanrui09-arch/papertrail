"""Domain prompt adaptation; reuse smolagents execution and existing local model adapter."""
import argparse
import json
from pathlib import Path
import time

from .data import write_json
from .discovery import DiscoverySession, make_tools
from .identifiers import sha256
from .paper_recommendation import load_recommender
from .retrieval import Corpus


def run(session: DiscoverySession, task: str, model: object) -> dict:
    from smolagents import ToolCallingAgent

    def source_selection_required(answer: object, agent: object) -> bool:
        selected = json.loads(answer) if isinstance(answer, str) else answer
        if not isinstance(selected, dict) or set(selected) != {"paper_ids"}:
            raise ValueError("Final answer must contain exactly paper_ids")
        ids = selected["paper_ids"]
        if not isinstance(ids, list) or any(not isinstance(x, str) for x in ids) or len(ids) > 5 or len(ids) != len(set(ids)):
            raise ValueError("Expected up to five unique paper ID strings")
        if not any(t["tool"] in ("recommend_papers", "search_papers") and "error" not in t["result"] for t in session.trace):
            raise ValueError("Retrieve recommendations or search results before final selection")
        read = {t["result"]["doc_id"] for t in session.trace if t["tool"] == "read_paper" and "error" not in t["result"]}
        if not set(ids).issubset(read):
            raise ValueError("Every final paper needs an original abstract read")
        return True

    agent = ToolCallingAgent(model=model, tools=make_tools(session), max_steps=6, max_tool_threads=1,
        instructions="Use the bound user's history; retrieve then read. Return only original paper IDs.",
        final_answer_checks=[source_selection_required], verbosity_level=1)
    prompt = Path(__file__).parent / "prompts/discovery.txt"
    agent.prompt_templates["system_prompt"] = prompt.read_text(encoding="utf-8")
    started, answer, error = time.perf_counter(), None, None
    try:
        answer = agent.run(task)
    except Exception as exc:
        error = type(exc).__name__+": "+str(exc)
    steps = [s.dict() for s in agent.memory.steps]
    exhausted = any(s.get("error", {}).get("type") == "AgentMaxStepsError" for s in steps if s.get("error"))
    checked = False
    if error is None and not exhausted:
        try:
            source_selection_required(answer, agent)
            checked = True
        except (ValueError, TypeError, json.JSONDecodeError):
            checked = False
    return {"answer": answer, "source_checked_selection": checked, "semantic_stance_verified": False,
            "error": error, "budget_exhausted": exhausted, "seconds": time.perf_counter()-started,
            "trace": session.trace, "steps": steps, "prompt_sha256": sha256(prompt),
            "scope": "one integration case, not Agent policy superiority or factual verification"}


def main() -> None:
    import torch
    from .local_model import LocalToolModel
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or not args.output.resolve().is_relative_to(Path("data").resolve()):
        raise ValueError("Use a new local-only data/ output path")
    torch.set_num_threads(4)
    model = LocalToolModel(model_id=".cache/models/Qwen2.5-1.5B-Instruct",
        device_map="cuda" if torch.cuda.is_available() else "cpu",
        torch_dtype="bfloat16" if torch.cuda.is_available() else "float32",
        model_kwargs={"local_files_only": True}, max_new_tokens=256, do_sample=False)
    session = DiscoverySession(load_recommender(), Corpus(Path("data/stage9-recommendation/documents.json")), args.user)
    report = run(session, args.task, model)
    write_json(args.output, report)
    print(json.dumps({k: report[k] for k in ("source_checked_selection", "budget_exhausted", "seconds", "error")}))


if __name__ == "__main__":
    main()
