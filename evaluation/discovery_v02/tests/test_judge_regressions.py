"""Independent regression cases: incomplete or fabricated reports never pass."""
import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("judge_regressions_target", ROOT / "judge.py")
judge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(judge)
CONTEXT = json.loads((ROOT / "fixtures/context.json").read_text(encoding="utf-8"))


def report(question_id="case-a"):
    return {
        "question_id": question_id, "synthetic": True, "project_id": "demo", "revision": 4,
        "error": None,
        "answer": {"action": "answer", "answer": "A regra atual usa peso bruto.",
                   "facts": {"rateio": "peso_bruto"}, "claim_ids": [], "relation_ids": [],
                   "evidence_ids": [], "abstained": False, "full_history_required": False},
        "retrieval": {"claim_ids": [], "relation_ids": [], "evidence_ids": [],
                      "source_ids": [], "calls": [], "units": 100, "budget": 8000,
                      "budget_exceeded": False, "count_method": "utf8_bytes_conservative"},
    }


@pytest.mark.parametrize("question_ids", [
    [],
    ["case-a"],
    ["case-a", "case-b", "case-a"],
    ["case-a", "case-b", "unexpected"],
], ids=["empty", "subset", "duplicate", "extra-question"])
def test_cli_rejects_incomplete_or_ambiguous_question_set(tmp_path, monkeypatch, question_ids):
    reports_path, expected_path, context_path, output_path = [tmp_path / name for name in
        ("reports.json", "expected.json", "context.json", "judgment.json")]
    reports_path.write_text(json.dumps({"reports": [report(qid) for qid in question_ids]}), encoding="utf-8")
    expected_path.write_text(json.dumps({qid: {"facts": {"rateio": "peso_bruto"}}
                                         for qid in ("case-a", "case-b")}), encoding="utf-8")
    context_path.write_text(json.dumps(CONTEXT), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["judge", str(reports_path), str(expected_path),
                                    str(context_path), "--output", str(output_path)])
    with pytest.raises((ValueError, SystemExit)) as failure:
        judge.main()
    if isinstance(failure.value, SystemExit):
        assert failure.value.code not in {None, 0}
    assert not output_path.exists(), "Invalid coverage must not emit a successful evaluation artifact"


def test_missing_required_evidence_is_extraction_failure_not_graphrag_evidence():
    sample = report()
    sample["answer"]["evidence_ids"] = ["ev_confirm"]
    sample["retrieval"]["evidence_ids"] = ["ev_confirm"]
    missing = copy.deepcopy(CONTEXT)
    missing["evidence"] = [item for item in missing["evidence"] if item["id"] != "ev_confirm"]
    expected = {"facts": {"rateio": "peso_bruto"}, "required_evidence_ids": ["ev_confirm"]}
    result = judge.evaluate(sample, expected, missing)
    assert not result["passed"]
    assert result["failure_stage"] == "extraction"
    assert "ev_confirm" in result["missing_context_ids"]
    assert not result["graphrag_comparison_candidate"]
    assert not result["graphrag_adopted"]


@pytest.mark.parametrize("citation_key,identifier,required_key", [
    ("claim_ids", "c_rateio", "required_claim_ids"),
    ("relation_ids", "r_frete_finance", "required_relation_ids"),
    ("evidence_ids", "ev_confirm", "required_evidence_ids"),
])
def test_required_citation_without_retrieval_cannot_pass(citation_key, identifier, required_key):
    sample = report()
    sample["answer"][citation_key] = [identifier]
    expected = {"facts": {"rateio": "peso_bruto"}, required_key: [identifier]}
    result = judge.evaluate(sample, expected, CONTEXT)
    assert not result["passed"], "A cited ID alone does not prove the consumer retrieved its content"
    assert not result["graphrag_adopted"]


@pytest.mark.parametrize("citation_key,identifier", [
    ("claim_ids", "c_rateio"), ("relation_ids", "r_frete_finance"), ("evidence_ids", "ev_confirm"),
])
def test_extra_unretrieved_citations_are_not_accepted(citation_key, identifier):
    sample = report()
    sample["answer"][citation_key] = [identifier]
    result = judge.evaluate(sample, {"facts": {"rateio": "peso_bruto"}}, CONTEXT)
    assert not result["passed"], "Correct facts cannot legitimize unsupported extra citations"


def test_partial_conservative_budget_failure_does_not_prove_eight_thousand_tokens():
    sample = report()
    sample["error"] = "context_budget_exceeded"
    sample["answer"] = None
    sample["retrieval"].update(units=3000, budget_exceeded=True, calls=[
        {"operation": "summary", "units": 3000, "accepted": True},
        {"operation": "topic", "id": "frete", "units": 6000, "accepted": False},
    ])
    result = judge.evaluate(sample, {"facts": {"rateio": "peso_bruto"}}, CONTEXT)
    assert not result["passed"]
    assert result["budget_evidence"] == "conservative_limit_only"
    assert result["budget_evidence"] != "counter_limit"
    assert not result["graphrag_adopted"]
