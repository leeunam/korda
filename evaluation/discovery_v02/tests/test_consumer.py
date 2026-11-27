"""The fake model proves budget/provenance mechanics, never model quality."""
import importlib.util
import json
from pathlib import Path

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


consumer = load("consumer")
judge = load("judge")
CONTEXT = json.loads((ROOT / "fixtures/context.json").read_text(encoding="utf-8"))


def client(*, revision=4, project="demo"):
    def respond(request):
        assert request.headers["authorization"] == "Bearer synthetic-token"
        assert "/revisions/4/" in request.url.path
        identity = {"project_id": project, "revision": revision}
        if request.url.path.endswith("/summary"):
            result = {"topics": [{"id": "fontes"}], "blockers": []}
        elif "/topics/" in request.url.path:
            result = {"claims": CONTEXT["claims"], "relations": CONTEXT["relations"]}
        elif "/evidence/" in request.url.path:
            eid = request.url.path.rsplit("/", 1)[-1]
            result = {"evidence": next(e for e in CONTEXT["evidence"] if e["id"] == eid)}
        elif request.url.path.endswith("/export"):
            result = CONTEXT
        else:
            return httpx.Response(404)
        return httpx.Response(200, json={**result, **identity})
    return httpx.Client(transport=httpx.MockTransport(respond))


class Model:
    model = "fake-consumer-for-mechanics"

    def __init__(self, actions):
        self.actions = iter(actions)
        self.last_usage = {}

    def __call__(self, system, data):
        body = json.loads(data)
        assert "expected" not in body and "gabarito" not in body
        return next(self.actions)


def answer(**changes):
    return {"action": "answer", "answer": "A regra usa peso bruto.",
            "facts": {"rateio": "peso_bruto"}, "claim_ids": [], "relation_ids": [],
            "evidence_ids": [], "abstained": False, "full_history_required": False, **changes}


def reader(**changes):
    return consumer.ContextReader("https://context.example", "demo", 4, "synthetic-token", client=client(), **changes)


def test_revision_and_project_are_checked_on_every_read():
    for bad in (client(revision=5), client(project="other")):
        view = consumer.ContextReader("https://context.example", "demo", 4, "synthetic-token", client=bad)
        with pytest.raises(ValueError, match="mixed"):
            view.read("summary")


def test_budget_counts_repeated_documents_before_exposing_them():
    view = reader(budget=100, count_tokens=lambda text: 60)
    view.read("summary")
    with pytest.raises(consumer.BudgetExceeded):
        view.read("summary")
    assert view.units == 60 and len(view.contents) == 1
    assert view.trace[-1]["accepted"] is False and view.budget_exceeded


def test_only_fixed_context_operations_and_https_are_allowed():
    view = reader()
    with pytest.raises(ValueError, match="Unsupported"):
        view.read("https://other.example/secrets")
    with pytest.raises(ValueError, match="HTTPS"):
        consumer.ContextReader("http://remote.example", "demo", 4, "token")


def test_multi_step_retrieval_reports_evidence_ids_without_full_context():
    model = Model([
        {"action": "read", "operation": "topic", "id": "frete"},
        {"action": "read", "operation": "evidence", "id": "ev_confirm"},
        answer(claim_ids=["c_rateio"], relation_ids=["r_frete_finance"], evidence_ids=["ev_confirm"]),
    ])
    result = consumer.run_consumer({"id": "owner", "text": "Qual o rateio?"}, reader(), model)
    assert result["error"] is None and result["model_calls"] == 3
    assert result["retrieval"]["evidence_ids"] == ["ev_confirm"]
    assert result["retrieval"]["source_ids"] == ["wamid.synthetic.input_confirm"]
    assert result["retrieval"]["count_method"] == "utf8_bytes_conservative"
    assert "retrieved" not in result and "synthetic-token" not in json.dumps(result)


def test_unretrieved_identifier_cannot_be_used_as_a_citation():
    result = consumer.run_consumer({"id": "invalid", "text": "Qual o rateio?"}, reader(),
                                   Model([answer(claim_ids=["c_rateio"])]))
    assert result["answer"] is None and result["error"] == "ValueError"


def report(**changes):
    return {"question_id": "owner", "project_id": "demo", "revision": 4,
            "answer": answer(claim_ids=["c_rateio"], relation_ids=["r_frete_finance"], evidence_ids=["ev_confirm"]),
            "error": None, "retrieval": {"claim_ids": ["c_rateio"], "relation_ids": ["r_frete_finance"],
                 "evidence_ids": ["ev_confirm"], "budget_exceeded": False, "count_method": "utf8_bytes_conservative"}, **changes}


def test_judge_separates_extraction_retrieval_and_interpretation():
    expected = {"facts": {"rateio": "peso_bruto"}, "required_claim_ids": ["c_rateio"],
                "required_relation_ids": ["r_frete_finance"], "required_evidence_ids": ["ev_confirm"]}
    good = report()
    assert judge.evaluate(good, expected, CONTEXT)["passed"]
    absent = {**CONTEXT, "relations": []}
    extraction = judge.evaluate(good, expected, absent)
    assert extraction["failure_stage"] == "extraction" and not extraction["graphrag_comparison_candidate"]
    missed = report(retrieval={**good["retrieval"], "relation_ids": []}, answer=None)
    retrieval = judge.evaluate(missed, expected, CONTEXT)
    assert retrieval["failure_stage"] == "retrieval" and retrieval["graphrag_comparison_candidate"]
    wrong = report(answer={**good["answer"], "facts": {"rateio": "volumes"}})
    interpretation = judge.evaluate(wrong, expected, CONTEXT)
    assert interpretation["failure_stage"] == "interpretation" and not interpretation["graphrag_comparison_candidate"]


def test_conservative_budget_is_not_claimed_as_exact_tokens_or_adoption():
    sample = report()
    sample["retrieval"]["budget_exceeded"] = True
    result = judge.evaluate(sample, {}, CONTEXT)
    assert result["budget_evidence"] == "conservative_limit_only"
    assert result["graphrag_adopted"] is False


def test_absent_information_requires_explicit_abstention():
    expected = {"facts": {"economia_comprovada": None}, "abstained": True}
    sample = report(answer=answer(facts={"economia_comprovada": None}, abstained=True))
    assert judge.evaluate(sample, expected, CONTEXT)["passed"]
    sample["answer"]["abstained"] = False
    assert not judge.evaluate(sample, expected, CONTEXT)["passed"]
