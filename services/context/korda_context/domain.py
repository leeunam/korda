"""Versioned interview context. Business authority belongs to the application."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator


NonEmpty = Annotated[str, Field(min_length=1)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


def identifier(project_id: str, kind: str, key: str) -> str:
    """Stable IDs are derived by the application, never accepted from a model."""
    return f"{kind}_{uuid5(NAMESPACE_URL, project_id + ':' + kind + ':' + key).hex}"


class Evidence(Model):
    id: NonEmpty
    input_id: NonEmpty
    participant_id: NonEmpty
    participant_role: NonEmpty
    kind: Literal["text", "audio_transcript"]
    source_id: NonEmpty
    input_timestamp: AwareDatetime
    quote: NonEmpty
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    transcription_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_locator(self):
        if self.end_offset - self.start_offset != len(self.quote):
            raise ValueError("evidence offsets must locate the exact quote")
        if self.kind == "audio_transcript" and self.transcription_version is None:
            raise ValueError("audio evidence requires a transcription version")
        if self.kind == "text" and self.transcription_version is not None:
            raise ValueError("text evidence cannot have a transcription version")
        return self


class Confirmation(Model):
    evidence_id: NonEmpty
    participant_id: NonEmpty
    role: NonEmpty


class Claim(Model):
    id: NonEmpty
    topic: NonEmpty
    key: NonEmpty
    kind: Literal["goal", "process", "source", "rule", "constraint", "decision"]
    statement: NonEmpty
    value: JsonValue
    unit: str | None = None
    time_scope: str | None = None
    state: Literal["declarada", "confirmada", "em_conflito", "substituida"] = "declarada"
    critical: bool
    evidence_ids: list[NonEmpty] = Field(min_length=1)
    confirmation: Confirmation | None = None
    superseded_by: str | None = None
    source_verification: Literal["nao_inspecionada"] | None = None
    inspected: Literal[False] = False

    @model_validator(mode="after")
    def validate_state(self):
        if self.value is None:
            raise ValueError("missing information belongs in a gap, not a claim")
        json.dumps(self.value, allow_nan=False)
        if self.kind == "source" and self.source_verification != "nao_inspecionada":
            raise ValueError("declared sources must remain not inspected")
        if self.state == "confirmada" and self.confirmation is None:
            raise ValueError("confirmed claims require an application confirmation")
        if self.state in {"declarada", "em_conflito"} and self.confirmation is not None:
            raise ValueError("pending or conflicting claims cannot carry a confirmation")
        if (self.state == "substituida") != (self.superseded_by is not None):
            raise ValueError("substituted claims require their successor")
        return self


class Entity(Model):
    id: NonEmpty
    topic: NonEmpty
    name: NonEmpty
    kind: NonEmpty
    evidence_ids: list[NonEmpty] = Field(min_length=1)


class Relation(Model):
    id: NonEmpty
    topic: NonEmpty
    source_id: NonEmpty
    target_id: NonEmpty
    kind: NonEmpty
    evidence_ids: list[NonEmpty] = Field(min_length=1)


class Gap(Model):
    id: NonEmpty
    topic: NonEmpty
    key: NonEmpty
    question: NonEmpty
    blocking: bool = True
    state: Literal["aberta", "a_confirmar", "respondida", "em_conflito"] = "aberta"
    claim_ids: list[NonEmpty] = Field(default_factory=list)
    evidence_ids: list[NonEmpty] = Field(default_factory=list)


class ContextDocument(Model):
    schema_version: Literal["0.2.0"] = "0.2.0"
    project_id: NonEmpty
    revision: int = Field(default=0, ge=0)
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    synthetic: Literal[True] = True
    interview_status: Literal["ativa", "pausada", "encerrada"] = "ativa"
    state: Literal["rascunho", "pronto"] = "rascunho"
    required_topics: dict[str, str] = Field(default_factory=dict)
    processed_input_ids: list[NonEmpty] = Field(default_factory=list)
    pending_input_ids: list[NonEmpty] = Field(default_factory=list)
    cutoff_sequence: int | None = Field(default=None, ge=0)
    evidence: list[Evidence] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_document(self):
        if any(not topic.strip() or not role.strip() for topic, role in self.required_topics.items()):
            raise ValueError("required topics and authority roles must not be empty")
        collections = (self.evidence, self.claims, self.entities, self.relations, self.gaps)
        all_ids = [item.id for group in collections for item in group]
        if len(all_ids) != len(set(all_ids)):
            raise ValueError("IDs must be unique throughout the context")
        evidence = {item.id: item for item in self.evidence}
        claims = {item.id: item for item in self.claims}
        entities = {item.id for item in self.entities}
        if len(self.processed_input_ids) != len(set(self.processed_input_ids)):
            raise ValueError("processed inputs must be unique")
        if len(self.pending_input_ids) != len(set(self.pending_input_ids)):
            raise ValueError("pending inputs must be unique")
        if set(self.processed_input_ids) & set(self.pending_input_ids):
            raise ValueError("an input cannot be both processed and pending")
        if any(item.input_id not in self.processed_input_ids for item in self.evidence):
            raise ValueError("evidence must reference a processed input")
        for group in (self.claims, self.entities, self.relations, self.gaps):
            for item in group:
                if not set(item.evidence_ids) <= evidence.keys():
                    raise ValueError("unknown evidence reference")
        for claim in self.claims:
            if claim.critical != (claim.topic in self.required_topics):
                raise ValueError("criticality must come from the project configuration")
            if claim.superseded_by:
                successor = claims.get(claim.superseded_by)
                if not successor or (successor.topic, successor.key) != (claim.topic, claim.key):
                    raise ValueError("invalid successor claim")
                visited = {claim.id}
                while successor is not None:
                    if successor.id in visited:
                        raise ValueError("claim successor history must not contain a cycle")
                    visited.add(successor.id)
                    successor = claims.get(successor.superseded_by) if successor.superseded_by else None
            if claim.confirmation:
                origin = evidence.get(claim.confirmation.evidence_id)
                if origin is None or origin.id not in claim.evidence_ids:
                    raise ValueError("confirmation must be supported by claim evidence")
                if (origin.participant_id, origin.participant_role) != (
                    claim.confirmation.participant_id, claim.confirmation.role
                ):
                    raise ValueError("confirmation identity must match its evidence")
                required_role = self.required_topics.get(claim.topic)
                if required_role and required_role != claim.confirmation.role:
                    raise ValueError("confirmation role is not authorized for this topic")
        for relation in self.relations:
            if relation.source_id not in entities or relation.target_id not in entities:
                raise ValueError("relation endpoints must reference existing entities")
        for gap in self.gaps:
            if not set(gap.claim_ids) <= claims.keys():
                raise ValueError("unknown gap claim reference")
            if any(claims[cid].topic != gap.topic for cid in gap.claim_ids):
                raise ValueError("gap claims must belong to the affected topic")
            if gap.topic in self.required_topics and not gap.blocking:
                raise ValueError("required-topic gaps must be blocking")
            if gap.state == "respondida" and (
                not gap.claim_ids or any(claims[cid].state != "confirmada" for cid in gap.claim_ids)
            ):
                raise ValueError("answered gaps require confirmed claims")
        if self.state == "pronto" and not ready(self):
            raise ValueError("ready context still contains missing or unconfirmed information")
        return self


def ready(context: ContextDocument) -> bool:
    if context.pending_input_ids or any(g.blocking and g.state != "respondida" for g in context.gaps):
        return False
    active = [claim for claim in context.claims if claim.state != "substituida"]
    return bool(context.required_topics) and all(
        any(c.topic == topic and c.state == "confirmada" for c in active)
        and all(c.state == "confirmada" for c in active if c.topic == topic)
        for topic in context.required_topics
    )


def new_context(project_id: str, required_topics: dict[str, str]) -> ContextDocument:
    gaps = [Gap(
        id=identifier(project_id, "gap", "required:" + topic), topic=topic, key="required",
        question=f"O que precisamos saber sobre {topic}?", blocking=True,
    ) for topic in required_topics]
    return ContextDocument(project_id=project_id, required_topics=required_topics, gaps=gaps)
