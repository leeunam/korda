"""Independent synthetic regressions for consent, conflicts and STT corrections."""

from datetime import datetime, timezone

import pytest

from korda_context.domain import new_context
from korda_context.organizer import Proposal, apply_proposal


ROLES = {"frete": "financeiro"}
OPERATIONS = {"id": "synthetic-operations", "role": "operacao"}
FINANCE = {"id": "synthetic-finance", "role": "financeiro"}
STAMP = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)
WEIGHT = "O rateio usa peso bruto."
VOLUME = "O rateio usa volumes."


def declaration(context, value, text, *, replaces=None, topic="frete", key="rateio"):
    claim = {"ref": "current", "topic": topic, "key": key, "kind": "rule",
             "statement": text, "value": value, "quote": text}
    if replaces is not None:
        claim["replaces_claim_id"] = replaces
    return {"base_revision": context.revision, "claims": [claim]}


def initial(*, audio=False):
    context = new_context("synthetic-semantic-regressions", ROLES)
    metadata = {"input_kind": "audio", "transcription_version": 1,
                "source_id": "wamid.synthetic-audio", "input_timestamp": STAMP} if audio else {}
    return apply_proposal(context, "original-input", WEIGHT, OPERATIONS,
                          declaration(context, "peso_bruto", WEIGHT), ROLES, **metadata)


def confirm(context, claim_id, *, text="Confirmo", participant=FINANCE, input_id="finance-confirmation"):
    return apply_proposal(context, input_id, text, participant,
                          {"base_revision": context.revision, "confirm_claim_ids": [claim_id]},
                          ROLES, [claim_id])


def test_conflict_can_select_existing_alternative_and_requires_fresh_authorized_confirmation():
    first = initial()
    weight_id = first.claims[0].id
    approved = confirm(first, weight_id)
    assert approved.state == "pronto"
    approved_snapshot = approved.model_dump(mode="json")

    conflict = apply_proposal(approved, "contradicting-input", VOLUME, OPERATIONS,
                             declaration(approved, "volumes", VOLUME), ROLES)
    volume_id = next(c.id for c in conflict.claims if c.value == "volumes")
    assert all(c.state == "em_conflito" for c in conflict.claims)
    before = conflict.model_dump(mode="json")

    text = "Correção: substituo o volume pelo peso bruto."
    corrected = apply_proposal(conflict, "correction-input", text, FINANCE,
                              declaration(conflict, "peso_bruto", text, replaces=volume_id), ROLES)
    active = [c for c in corrected.claims if c.state != "substituida"]
    assert len(active) == 1
    assert active[0].id == weight_id and active[0].state == "declarada"
    assert active[0].confirmation is None
    assert corrected.state == "rascunho"
    assert {c.id for c in corrected.claims} == {c.id for c in conflict.claims}
    previous_volume = next(c for c in corrected.claims if c.id == volume_id)
    assert previous_volume.state == "substituida" and previous_volume.superseded_by == weight_id
    assert {e.id for e in conflict.evidence} <= {e.id for e in corrected.evidence}
    assert {g.id for g in conflict.gaps} == {g.id for g in corrected.gaps}

    with pytest.raises(ValueError):
        confirm(corrected, weight_id, participant=OPERATIONS, input_id="unauthorized-confirmation")
    completed = confirm(corrected, weight_id, input_id="fresh-finance-confirmation")
    assert completed.state == "pronto" and all(g.state == "respondida" for g in completed.gaps)
    assert next(c for c in completed.claims if c.id == weight_id).confirmation.participant_id == FINANCE["id"]
    assert approved.model_dump(mode="json") == approved_snapshot
    assert conflict.model_dump(mode="json") == before


@pytest.mark.parametrize("text", [
    "Confirmo se o financeiro concordar.",
    "A palavra confirmo é apenas um exemplo, não minha resposta.",
    "Confirmo o rateio por volumes.",
    "Confirmo o peso bruto, mas precisamos verificar.",
])
def test_conditional_metalinguistic_or_different_value_is_not_consent(text):
    context = initial()
    before = context.model_dump(mode="json")
    with pytest.raises(ValueError):
        confirm(context, context.claims[0].id, text=text)
    assert context.model_dump(mode="json") == before


def test_authenticated_stt_correction_changes_fact_without_fabricating_words_in_transcript():
    original = initial(audio=True)
    old_id = original.claims[0].id
    approved = confirm(original, old_id)
    before = approved.model_dump(mode="json")
    corrected = apply_proposal(
        approved, "corrected-audio-input", VOLUME, OPERATIONS,
        declaration(approved, "volumes", VOLUME, replaces=old_id), ROLES,
        input_kind="audio", transcription_version=2, source_id="wamid.synthetic-audio",
        input_timestamp=STAMP, correction_input_ids=["original-input"],
    )
    assert corrected.state == "rascunho"
    old = next(c for c in corrected.claims if c.id == old_id)
    new = next(c for c in corrected.claims if c.id != old_id)
    assert old.state == "substituida" and old.superseded_by == new.id
    assert old.confirmation == approved.claims[0].confirmation
    assert new.value == "volumes" and new.state == "declarada" and new.confirmation is None
    assert {e.id for e in approved.evidence} <= {e.id for e in corrected.evidence}
    original_evidence = next(e for e in corrected.evidence if e.input_id == "original-input")
    corrected_evidence = next(e for e in corrected.evidence if e.input_id == "corrected-audio-input")
    assert original_evidence.quote == WEIGHT and original_evidence.transcription_version == 1
    assert corrected_evidence.quote == VOLUME and corrected_evidence.transcription_version == 2
    assert original_evidence.source_id == corrected_evidence.source_id == "wamid.synthetic-audio"
    assert approved.model_dump(mode="json") == before

    with pytest.raises(ValueError):
        confirm(corrected, new.id, participant=OPERATIONS, input_id="operations-cannot-approve")
    completed = confirm(corrected, new.id, input_id="finance-confirms-corrected-rule")
    assert completed.state == "pronto"
    assert next(c for c in completed.claims if c.id == new.id).confirmation.role == "financeiro"


@pytest.mark.parametrize("authority", ["unrelated-audio", "text-evidence", "other-participant"])
def test_technical_correction_cannot_reuse_unrelated_evidence_or_identity(authority):
    context = initial(audio=authority != "text-evidence")
    original_id = context.claims[0].id
    correction_ids = ["original-input"]
    actor = OPERATIONS
    if authority == "unrelated-audio":
        text = "O processo termina na entrega."
        context = apply_proposal(
            context, "other-audio-input", text, OPERATIONS,
            declaration(context, "entrega", text, topic="processo", key="fim"), ROLES,
            input_kind="audio", transcription_version=1, source_id="wamid.other-audio", input_timestamp=STAMP,
        )
        correction_ids = ["other-audio-input"]
    elif authority == "other-participant":
        actor = {"id": "synthetic-unrelated-operations", "role": "operacao"}
    before = context.model_dump(mode="json")
    with pytest.raises(ValueError):
        apply_proposal(
            context, "invalid-correction-input", VOLUME, actor,
            declaration(context, "volumes", VOLUME, replaces=original_id), ROLES,
            input_kind="audio", transcription_version=2, source_id="wamid.synthetic-audio",
            input_timestamp=STAMP, correction_input_ids=correction_ids,
        )
    assert context.model_dump(mode="json") == before


def test_model_cannot_assign_itself_trusted_correction_authority():
    context = initial(audio=True)
    forged = declaration(context, "volumes", VOLUME, replaces=context.claims[0].id)
    forged["correction_input_ids"] = ["original-input"]
    with pytest.raises(ValueError):
        Proposal.model_validate(forged)
