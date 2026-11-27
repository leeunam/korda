"""A phone identifies a participant, not one exclusive area of authority."""
import json

import pytest

from korda_context.cli import parser
from korda_context.domain import new_context
from korda_context.interview import Interviewer
from korda_context.organizer import Organizer, apply_proposal


TOPICS = {"processo": "operacao", "frete_rateio": "financeiro"}
COMBINED = {"id": "synthetic-combined", "role": "operacao", "roles": ["operacao", "financeiro"]}
OPERATIONS = {"id": "synthetic-operations", "role": "operacao"}
FINANCE = {"id": "synthetic-finance", "role": "financeiro"}
TEXT = "O processo usa um TMS e o rateio usa peso."


def no_model(*_):
    raise AssertionError("Confirmation selection belongs to the backend")


def declare(participant):
    return apply_proposal(new_context("synthetic-demo", TOPICS), "declaration", TEXT, participant, {
        "base_revision": 0,
        "claims": [{"ref": topic, "topic": topic, "key": "regra", "kind": "rule",
                    "statement": TEXT, "quote": TEXT, "value": value}
                   for topic, value in (("processo", "TMS"), ("frete_rateio", "peso"))],
    }, TOPICS)


REVERSED = {**COMBINED, "role": "financeiro", "roles": ["financeiro", "operacao"]}


@pytest.mark.parametrize("participants", [(COMBINED, COMBINED), (REVERSED, REVERSED), (OPERATIONS, FINANCE)])
def test_one_participant_with_both_roles_or_two_participants_can_complete_context(participants):
    context = declare(participants[0])
    original = context.model_dump(mode="json")
    for index, participant in enumerate(participants):
        question = Interviewer(no_model).choose(context, participant)
        assert question.topic == ("processo", "frete_rateio")[index]
        context = apply_proposal(context, f"confirmation-{index}", "Confirmo", participant, {
            "base_revision": context.revision, "confirm_claim_ids": question.claim_ids,
        }, TOPICS, question.claim_ids)
    assert context.state == "pronto"
    assert {c.topic: c.confirmation.role for c in context.claims} == TOPICS
    assert original["claims"][0]["state"] == "declarada"
    assert context.claims[0].id == original["claims"][0]["id"]
    if len(participants[0].get("roles", [])) == 2:
        # One quote supporting both areas needs distinct effective roles on its evidence.
        assert len(original["evidence"]) == 2
        assert {e["participant_role"] for e in original["evidence"]} == {"operacao", "financeiro"}


def test_primary_role_does_not_hide_financial_authority_in_model_payloads():
    captured = []
    Organizer(lambda _, data: captured.append(json.loads(data)) or {"base_revision": 0}).propose(
        new_context("synthetic-demo", TOPICS), TEXT, COMBINED)
    interviewer = Interviewer(lambda _, data: captured.append(json.loads(data)) or {"text": "Como funciona o processo?"})
    interviewer.choose(new_context("synthetic-demo", TOPICS), COMBINED)
    assert all(c["participant"]["roles"] == ["operacao", "financeiro"] for c in captured)


def test_single_role_cannot_confirm_or_replace_financial_rule():
    context = declare(COMBINED)
    finance = next(c for c in context.claims if c.topic == "frete_rateio")
    for change, text in (({"confirm_claim_ids": [finance.id]}, "Confirmo"),
                         ({"claims": [{"ref": "correction", "topic": finance.topic, "key": finance.key,
                            "kind": "rule", "statement": "Corrigindo: rateio por volume.", "value": "volume",
                            "quote": "Corrigindo: rateio por volume.", "replaces_claim_id": finance.id}]},
                          "Corrigindo: rateio por volume.")):
        with pytest.raises(ValueError, match="role cannot confirm|not authorized"):
            apply_proposal(context, "unauthorized", text, {**OPERATIONS, "name": "Sou financeiro"},
                           {"base_revision": context.revision, **change}, TOPICS, [finance.id])


def test_cli_accepts_repeated_roles_for_one_phone():
    args = parser().parse_args(["participant-add", "demo", "--wa-id", "synthetic-phone",
                               "--name", "Responsável sintético", "--role", "operacao", "--role", "financeiro"])
    assert args.role == ["operacao", "financeiro"]


def test_combined_participant_can_correct_finance_without_self_confirmation():
    context = declare(COMBINED)
    finance = next(c for c in context.claims if c.topic == "frete_rateio")
    text = "Corrigindo: rateio por volume."
    after = apply_proposal(context, "correction", text, COMBINED, {
        "base_revision": context.revision,
        "claims": [{"ref": "correction", "topic": finance.topic, "key": finance.key, "kind": "rule",
                    "statement": text, "quote": text, "value": "volume", "replaces_claim_id": finance.id}],
    }, TOPICS)
    assert next(c for c in after.claims if c.id == finance.id).state == "substituida"
    successor = next(c for c in after.claims if c.value == "volume")
    assert successor.state == "declarada" and successor.confirmation is None
    assert next(e for e in after.evidence if e.id in successor.evidence_ids).participant_role == "financeiro"
