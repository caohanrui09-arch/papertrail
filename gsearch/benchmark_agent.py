"""Small, predeclared tuning audit; labels are used only AFTER the agent runs."""
import argparse
import json
from pathlib import Path

import torch

from .agent import EvidenceSession, run_agent
from .data import write_json
from .local_model import LocalToolModel
from .retrieval import BM25, Corpus, GenerativeRetriever, Hybrid


def score_report(report: dict, gold: dict) -> dict:
    # Existence/quote checks were performed by the tools. Evaluate meaning separately.
    relevant = gold["evidence"]
    recorded = report["evidence"]
    correct_documents = {r["doc_id"] for r in recorded if r["doc_id"] in relevant}
    complete_rationale_with_correct_stance = False
    for entry in recorded:
        for rationale in relevant.get(entry["doc_id"], []):
            if (rationale["label"] == entry["model_stance"]
                    and set(rationale["sentences"]).issubset(entry["sentence_ids"])):
                complete_rationale_with_correct_stance = True
    abstained = "INSUFFICIENT" in str(report["answer"]).upper()
    return {"claim_id": gold["id"], "has_gold_evidence": bool(relevant),
            "recorded_document_recall": len(correct_documents) / len(relevant) if relevant else None,
            "complete_rationale_and_stance": complete_rationale_with_correct_stance,
            "explicit_abstention": abstained,
            "no_evidence_abstention": abstained and not recorded if not relevant else None,
            "successful_tool_calls": sum("error" not in t["result"] for t in report["tool_trace"]),
            "failed_tool_calls": sum("error" in t["result"] for t in report["tool_trace"]),
            "model_parsing_or_execution_errors": sum(bool(s.get("error")) for s in report["agent_steps"]),
            "seconds": report["seconds"], "budget_exhausted": report["budget_exhausted"],
            "completed_protocol": report.get("completed_protocol", False)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("data/prepared"))
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--model", type=Path, default=Path(".cache/models/Qwen2.5-1.5B-Instruct"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--prompt-profile", choices=["domain", "generic"], default="domain")
    parser.add_argument("--positive", type=int, default=3)
    parser.add_argument("--negative", type=int, default=1)
    parser.add_argument("--verifier-config", type=Path)
    parser.add_argument("--split", choices=["tuning", "dev"], default="tuning")
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Refusing to overwrite existing benchmark")
    args.output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(4)
    corpus = Corpus(args.data / "documents.json")
    lexical = BM25(corpus)
    neural = GenerativeRetriever(corpus, args.checkpoint)
    retrievers = {"bm25": lexical, "dsi": neural, "hybrid": Hybrid(lexical, neural)}
    verifier = None
    if args.verifier_config:
        from .verification import RerankedRetriever, load_verifier
        verifier = load_verifier(corpus, args.verifier_config)
        retrievers["hybrid_checked"] = RerankedRetriever(corpus, retrievers["hybrid"], verifier.relevance)
    tuning = json.loads((args.data / f"{args.split}.json").read_text(encoding="utf-8"))
    # Predeclared ID order, no selection based on observed agent success.
    selected = sorted((c for c in tuning if c["evidence"]), key=lambda c: c["id"])[:args.positive]
    selected += sorted((c for c in tuning if not c["evidence"]), key=lambda c: c["id"])[:args.negative]
    write_json(args.output / "selection.json", {"split": args.split, "claim_ids": [c["id"] for c in selected],
                                               "verifier_config": str(args.verifier_config),
                                               "selection": "lowest IDs, with and without evidence, before model runs"})
    model = LocalToolModel(model_id=str(args.model), device_map="cuda" if torch.cuda.is_available() else "cpu",
                           torch_dtype="bfloat16" if torch.cuda.is_available() else "float32",
                           model_kwargs={"local_files_only": True}, max_new_tokens=320, do_sample=False)
    model.model.generation_config.temperature = 1.0
    model.model.generation_config.top_p = 1.0
    model.model.generation_config.top_k = 50
    scores = []
    for claim in selected:
        report = run_agent(EvidenceSession(corpus, retrievers, verifier=verifier), claim["claim"], model, args.steps, args.prompt_profile)
        report.update({"claim_id": claim["id"], "split": args.split, "retrieval_checkpoint": str(args.checkpoint)})
        write_json(args.output / f"claim-{claim['id']}.json", report)
        scores.append(score_report(report, claim))
        write_json(args.output / "scores.json", {"scope": f"small_{args.split}_agent_audit_not_a_population_success_estimate",
                                                "cases": scores})
        print(json.dumps(scores[-1]), flush=True)


if __name__ == "__main__":
    main()
