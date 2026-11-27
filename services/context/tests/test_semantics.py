"""Trust-boundary and history checks for interview context, without paid providers."""

from datetime import datetime, timezone
import importlib.util
from pathlib import Path

import pytest

from korda_context.domain import ContextDocument, identifier, new_context
from korda_context.organizer import Organizer, Proposal, apply_proposal
from korda_context import retrieval


ROLES = {"frete": "financeiro"}
OPERATOR = {"id": "operacao-sintetica", "role": "operacao"}
FINANCE = {"id": "financeiro-sintetico", "role": "financeiro"}
DECLARATION = "O frete é rateado pelo peso bruto do pedido."
CONFIRMATION = "Confirmo o rateio pelo peso bruto do pedido."


def proposal(revision=0, *, value="peso_bruto", quote=DECLARATION, **changes):
    return {"base_revision": revision, "claims": [{
        "ref": "rateio", "topic": "frete", "key": "rateio", "kind": "rule",
        "statement": "O frete usa o peso bruto do pedido no rateio.",
        "value": value, "quote": quote, **changes,
    }]}


def declared():
    return apply_proposal(new_context("empresa-sintetica", ROLES), "turno1", DECLARATION,
                          OPERATOR, proposal(), ROLES)


def confirmed():
    first = declared()
    return apply_proposal(first, "turno2", CONFIRMATION, FINANCE,
                          {"base_revision": 1, "confirm_claim_ids": [first.claims[0].id]},
                          ROLES, [first.claims[0].id])


def test_missing_information_stays_missing_and_initial_context_is_blocked():
    context = new_context("empresa-sintetica", ROLES)
    assert context.claims == []
    assert context.gaps[0].state == "aberta"
    assert context.state == "rascunho"
    assert context.gaps[0].blocking


def test_declaration_does_not_confirm_itself_and_provenance_is_literal():
    context = declared()
    assert context.claims[0].state == "declarada"
    assert context.claims[0].confirmation is None
    assert context.state == "rascunho"
    assert context.evidence[0].quote == DECLARATION
    assert context.evidence[0].participant_role == "operacao"
    assert context.evidence[0].end_offset == len(DECLARATION)


def test_finance_confirmation_resolves_same_gap_and_preserves_evidence():
    before, after = declared(), confirmed()
    assert after.revision == 2 and after.state == "pronto"
    assert after.claims[0].id == before.claims[0].id
    assert set(before.claims[0].evidence_ids) < set(after.claims[0].evidence_ids)
    assert after.claims[0].confirmation.role == "financeiro"
    assert after.gaps[0].id == before.gaps[0].id
    assert all(g.state == "respondida" for g in after.gaps)
    assert before.claims[0].state == "declarada"


@pytest.mark.parametrize("participant,pending,text", [
    (OPERATOR, True, CONFIRMATION),
    (FINANCE, False, CONFIRMATION),
    (FINANCE, True, "Não confirmo esse critério."),
    (FINANCE, True, "Sim, mas depende do cliente."),
])
def test_confirmation_requires_role_pending_challenge_and_explicit_agreement(participant, pending, text):
    before = declared()
    with pytest.raises(ValueError):
        apply_proposal(before, "turno2", text, participant,
                       {"base_revision": 1, "confirm_claim_ids": [before.claims[0].id]},
                       ROLES, [before.claims[0].id] if pending else [])
    assert before.revision == 1 and before.claims[0].state == "declarada"


def test_fabricated_quote_or_stale_revision_cannot_partially_mutate_context():
    initial = new_context("empresa-sintetica", ROLES)
    with pytest.raises(ValueError, match="quote absent"):
        apply_proposal(initial, "turno1", "Não sei o critério.", OPERATOR, proposal(), ROLES)
    with pytest.raises(ValueError, match="stale"):
        apply_proposal(initial, "turno1", DECLARATION, OPERATOR, proposal(revision=3), ROLES)
    assert initial.revision == 0 and initial.evidence == []


def test_model_cannot_confirm_a_claim_created_in_the_same_turn_or_assign_a_role():
    initial = new_context("empresa-sintetica", ROLES)
    changes = proposal()
    changes["confirm_claim_ids"] = [identifier(initial.project_id, "claim", "turno1:rateio")]
    with pytest.raises(ValueError, match="previously sent"):
        apply_proposal(initial, "turno1", DECLARATION, FINANCE, changes, ROLES)
    changes = proposal()
    changes["claims"][0]["confirmed_by"] = {"role": "financeiro"}
    with pytest.raises(ValueError):
        Proposal.model_validate(changes)


def test_json_boolean_and_number_are_not_deduplicated_as_the_same_fact():
    first = apply_proposal(new_context("empresa-sintetica", ROLES), "turno1", DECLARATION,
                           OPERATOR, proposal(value=True), ROLES)
    second = apply_proposal(first, "turno2", DECLARATION, OPERATOR,
                            proposal(1, value=1), ROLES)
    assert len(second.claims) == 2
    assert all(claim.state == "em_conflito" for claim in second.claims)
    with pytest.raises(ValueError):
        apply_proposal(new_context("empresa-sintetica", ROLES), "turno1", DECLARATION,
                       OPERATOR, proposal(value=float("nan")), ROLES)


def test_contradiction_preserves_both_alternatives_and_blocks_context():
    before = confirmed()
    text = "O frete é dividido pelo volume do pedido."
    after = apply_proposal(before, "turno3", text, OPERATOR,
                           proposal(2, value="volume", quote=text), ROLES)
    assert len(after.claims) == 2
    assert {c.value for c in after.claims} == {"peso_bruto", "volume"}
    assert all(c.state == "em_conflito" for c in after.claims)
    assert after.state == "rascunho"
    assert any(g.state == "em_conflito" and g.blocking for g in after.gaps)
    assert {e.id for e in before.evidence} <= {e.id for e in after.evidence}


def test_authorized_correction_creates_successor_and_requires_new_confirmation():
    before = confirmed()
    text = "Corrigindo: o rateio deve usar o volume do pedido."
    after = apply_proposal(before, "turno3", text, FINANCE,
                           proposal(2, value="volume", quote=text, replaces_claim_id=before.claims[0].id), ROLES)
    assert after.claims[0].state == "substituida"
    assert after.claims[0].confirmation == before.claims[0].confirmation
    assert after.claims[0].superseded_by == after.claims[1].id
    assert after.claims[1].state == "declarada" and after.state == "rascunho"
    final = apply_proposal(after, "turno4", "Confirmo o rateio por volume.", FINANCE,
                           {"base_revision": 3, "confirm_claim_ids": [after.claims[1].id]},
                           ROLES, [after.claims[1].id])
    assert final.state == "pronto"
    assert all(g.state == "respondida" for g in final.gaps)


def test_same_fact_keeps_its_id_and_duplicate_input_is_idempotent():
    before = declared()
    after = apply_proposal(before, "turno2", DECLARATION, OPERATOR, proposal(1), ROLES)
    assert len(after.claims) == 1 and after.claims[0].id == before.claims[0].id
    assert len(after.claims[0].evidence_ids) == 2
    again = apply_proposal(after, "turno2", DECLARATION, OPERATOR, proposal(1), ROLES)
    assert again == after


def test_audio_evidence_keeps_source_timestamp_and_transcription_version():
    stamp = datetime(2026, 11, 27, 12, 30, tzinfo=timezone.utc)
    context = apply_proposal(new_context("empresa-sintetica", ROLES), "audio1", DECLARATION,
                             OPERATOR, proposal(), ROLES, input_kind="audio", source_id="mid-sintetica",
                             transcription_version=2, input_timestamp=stamp)
    evidence = context.evidence[0]
    assert evidence.kind == "audio_transcript" and evidence.transcription_version == 2
    assert evidence.input_timestamp == stamp and evidence.source_id == "mid-sintetica"
    with pytest.raises(ValueError, match="transcription version"):
        apply_proposal(new_context("empresa-sintetica", ROLES), "audio1", DECLARATION,
                       OPERATOR, proposal(), ROLES, input_kind="audio")


def test_declared_sources_cannot_become_inspected():
    changes = {"base_revision": 0, "claims": [{
        "ref": "erp", "topic": "fontes", "key": "erp", "kind": "source",
        "statement": "O ERP armazena pedidos.", "value": "ERP", "quote": "Usamos ERP.",
    }]}
    context = apply_proposal(new_context("empresa-sintetica", ROLES), "turno1", "Usamos ERP.",
                             OPERATOR, changes, ROLES)
    assert context.claims[0].source_verification == "nao_inspecionada"
    forged = context.model_dump()
    forged["claims"][0]["inspected"] = True
    with pytest.raises(ValueError):
        ContextDocument.model_validate(forged)


def test_relations_are_navigable_and_views_are_revision_pinned_without_full_history():
    text = "O cálculo do frete usa os pedidos do ERP."
    changes = {"base_revision": 0, "entities": [
        {"ref": "cost", "topic": "frete", "name": "Custo de frete", "kind": "indicator", "quote": text},
        {"ref": "erp", "topic": "fontes", "name": "ERP", "kind": "system", "quote": text},
    ], "relations": [{"topic": "frete", "source_ref": "cost", "target_ref": "erp", "kind": "uses", "quote": text}]}
    context = apply_proposal(new_context("empresa-sintetica", ROLES), "turno1", text, OPERATOR, changes, ROLES)
    sources = retrieval.topic(context, "fontes")
    assert len(sources["relations"]) == 1 and len(sources["entities"]) == 2
    assert text not in str(sources)
    item = retrieval.evidence(context, sources["evidence_ids"][0])
    assert item["evidence"]["quote"] == text
    views = [retrieval.overview(context), sources, item, retrieval.export(context)]
    assert all(view["revision"] == 1 and view["project_id"] == context.project_id for view in views)
    assert all(view.get("blockers") for view in views[:2])
    with pytest.raises(KeyError):
        retrieval.topic(context, "nao-existe")


def test_pending_input_or_unconfirmed_information_prevents_ready_export():
    forged = confirmed().model_dump()
    forged["pending_input_ids"] = ["audio-pendente"]
    with pytest.raises(ValueError, match="ready context"):
        ContextDocument.model_validate(forged)
    forged = declared().model_dump()
    forged["claims"][0]["evidence_ids"] = ["evidencia-inventada"]
    with pytest.raises(ValueError, match="unknown evidence"):
        ContextDocument.model_validate(forged)


def test_organizer_passes_only_current_input_and_schema_to_provider():
    calls = []
    def generate(system, payload):
        calls.append((system, payload))
        return proposal()
    organizer = Organizer(generate)
    result = organizer.organize(new_context("empresa-sintetica", ROLES), "turno1", DECLARATION,
                                OPERATOR, ROLES)
    assert result.claims[0].value == "peso_bruto"
    assert "base_revision" in calls[0][0] and "current_text" in calls[0][1]


def test_contract_validator_rejects_lost_or_rewritten_history():
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location("contract02", root / "packages/contracts/context/v0.2.0/validate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    before = declared()
    after = apply_proposal(before, "turno2", CONFIRMATION, FINANCE,
                           {"base_revision": 1, "confirm_claim_ids": [before.claims[0].id]},
                           ROLES, [before.claims[0].id])
    module.validate(after.model_dump(mode="json"), before.model_dump(mode="json"))
    broken = after.model_dump(mode="json")
    broken["evidence"][0]["quote"] = "Frase inventada do mesmo tamanho para teste!!"
    broken["evidence"][0]["end_offset"] = len(broken["evidence"][0]["quote"])
    with pytest.raises(ValueError, match="evidence history"):
        module.validate(broken, before.model_dump(mode="json"))
