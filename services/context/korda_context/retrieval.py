"""Deterministic, revision-pinned views; relations remain navigable without GraphRAG."""

from .domain import ContextDocument


def _document(context: ContextDocument | dict) -> dict:
    return ContextDocument.model_validate(context).model_dump(mode="json")


def _identity(document: dict) -> dict:
    return {key: document[key] for key in ("schema_version", "project_id", "revision", "synthetic")}


def _blockers(document: dict) -> list[dict]:
    return [gap for gap in document["gaps"] if gap["blocking"] and gap["state"] != "respondida"]


def overview(context: ContextDocument | dict) -> dict:
    document = _document(context)
    topics = sorted(set(document["required_topics"]) | {
        item["topic"] for collection in ("claims", "entities", "relations", "gaps")
        for item in document[collection]
    })
    return {
        **_identity(document), "state": document["state"], "interview_status": document["interview_status"],
        "pending_input_ids": document["pending_input_ids"],
        "cutoff_sequence": document["cutoff_sequence"],
        "goals": [c for c in document["claims"] if c["kind"] == "goal" and c["state"] != "substituida"],
        "decisions": [c for c in document["claims"] if c["kind"] == "decision" and c["state"] != "substituida"],
        "topics": [{"id": topic_id, "claim_ids": [c["id"] for c in document["claims"] if c["topic"] == topic_id],
                    "relation_ids": [r["id"] for r in document["relations"] if r["topic"] == topic_id]}
                   for topic_id in topics],
        "blockers": _blockers(document),
    }


def topic(context: ContextDocument | dict, topic_id: str) -> dict:
    document = _document(context)
    claims = [c for c in document["claims"] if c["topic"] == topic_id]
    relations = [r for r in document["relations"] if r["topic"] == topic_id]
    entity_ids = {eid for r in relations for eid in (r["source_id"], r["target_id"])}
    entities = [e for e in document["entities"] if e["topic"] == topic_id or e["id"] in entity_ids]
    # Include cross-topic edges touching a topic entity, not merely edges labelled with that topic.
    entity_ids.update(e["id"] for e in entities)
    relations = [r for r in document["relations"] if r["topic"] == topic_id or
                 r["source_id"] in entity_ids or r["target_id"] in entity_ids]
    entity_ids.update(eid for r in relations for eid in (r["source_id"], r["target_id"]))
    entities = [e for e in document["entities"] if e["id"] in entity_ids]
    gaps = [g for g in document["gaps"] if g["topic"] == topic_id]
    if not (claims or relations or entities or gaps or topic_id in document["required_topics"]):
        raise KeyError(topic_id)
    evidence_ids = sorted({eid for group in (claims, relations, entities, gaps) for item in group for eid in item["evidence_ids"]})
    return {**_identity(document), "topic": topic_id, "claims": claims, "entities": entities,
            "relations": relations, "gaps": gaps, "evidence_ids": evidence_ids,
            "related_topic_ids": sorted({e["topic"] for e in entities} | {r["topic"] for r in relations}),
            "blockers": _blockers(document)}


def evidence(context: ContextDocument | dict, evidence_id: str) -> dict:
    document = _document(context)
    item = next((e for e in document["evidence"] if e["id"] == evidence_id), None)
    if item is None:
        raise KeyError(evidence_id)
    return {**_identity(document), "evidence": item,
            "claim_ids": [c["id"] for c in document["claims"] if evidence_id in c["evidence_ids"]],
            "relation_ids": [r["id"] for r in document["relations"] if evidence_id in r["evidence_ids"]]}


def export(context: ContextDocument | dict) -> dict:
    return _document(context)
