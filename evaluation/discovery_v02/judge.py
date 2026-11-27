"""Independent evaluator: answer keys are opened here, never by the consumer."""
import argparse
import json
from pathlib import Path


def evaluate(report: dict, expected: dict, context: dict) -> dict:
    if report["project_id"] != context["project_id"] or report["revision"] != context["revision"]:
        raise ValueError("Evaluator must use exactly the consumer's context revision")
    answer = report.get("answer") or {}
    retrieval = report["retrieval"]
    context_relations = {r["id"] for r in context["relations"]}
    context_claims = {c["id"] for c in context["claims"]}
    required_relations = set(expected.get("required_relation_ids", []))
    required_claims = set(expected.get("required_claim_ids", []))
    required_evidence = set(expected.get("required_evidence_ids", []))
    absent = (required_relations - context_relations) | (required_claims - context_claims)
    missing_retrieval = (required_relations - set(retrieval["relation_ids"])) | (required_claims - set(retrieval["claim_ids"]))
    missing_citations = (required_relations - set(answer.get("relation_ids", []))) | (required_claims - set(answer.get("claim_ids", []))) | (required_evidence - set(answer.get("evidence_ids", [])))
    facts_correct = all(key in answer.get("facts", {}) and answer["facts"][key] == value
                        for key, value in expected.get("facts", {}).items())
    abstention_correct = answer.get("abstained") == expected.get("abstained", False)
    passed = not report.get("error") and not absent and not missing_citations and facts_correct and abstention_correct
    if absent:
        failure = "extraction"
    elif missing_retrieval:
        failure = "retrieval"
    elif not passed:
        failure = "interpretation"
    else:
        failure = None
    budget = retrieval.get("budget_exceeded", False)
    history = bool(answer.get("full_history_required"))
    graph_candidate = not absent and ((bool(required_relations) and failure == "retrieval") or budget or history)
    return {"question_id": report["question_id"], "passed": passed, "failure_stage": failure,
            "missing_context_ids": sorted(absent), "missing_retrieval_ids": sorted(missing_retrieval),
            "missing_citation_ids": sorted(missing_citations), "facts_correct": facts_correct,
            "graphrag_comparison_candidate": graph_candidate,
            "graphrag_adopted": False,
            "budget_evidence": "conservative_limit_only" if budget and retrieval.get("count_method") == "utf8_bytes_conservative" else ("counter_limit" if budget else None),
            "next_action": "Compare on the same questions, revision, model and budget; inspect extraction first" if graph_candidate else "No retrieval evidence requiring GraphRAG in this case"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", type=Path)
    parser.add_argument("expected", type=Path)
    parser.add_argument("context", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    reports = json.loads(args.reports.read_text(encoding="utf-8"))["reports"]
    expected = json.loads(args.expected.read_text(encoding="utf-8"))
    context = json.loads(args.context.read_text(encoding="utf-8"))
    results = [evaluate(report, expected[report["question_id"]], context) for report in reports]
    args.output.write_text(json.dumps({"synthetic": True, "graphrag_adopted": False, "results": results},
                                     ensure_ascii=False, indent=2), encoding="utf-8")
    if not all(result["passed"] for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
