"""Public HTTP boundaries: authentication, signed batches and pinned revisions."""
import hashlib
import hmac
import json

from fastapi.testclient import TestClient
import pytest

from korda_context.api import create_app
from korda_context.config import Settings
from korda_context.domain import new_context
from korda_context.organizer import apply_proposal
from korda_context.persistence import UnknownParticipant


TOKEN = "synthetic-project-token-with-32-characters"
SECRET = "synthetic-meta-test-secret"


class MemoryRepository:
    """HTTP boundary fake only; persistence behavior is tested with PostgreSQL."""
    def __init__(self):
        context = new_context("demo", {"frete": "financeiro"})
        self.document = apply_proposal(context, "input-01", "O financeiro usa peso.",
            {"id": "finance", "role": "financeiro"}, {"base_revision": 0, "claims": [{
                "ref": "rule", "topic": "frete", "key": "rateio", "kind": "rule",
                "statement": "O rateio usa peso", "value": "peso", "quote": "usa peso"}]},
            {"frete": "financeiro"}).model_dump(mode="json")
        self.inputs, self.deliveries = {}, []

    def health(self):
        return True

    def authenticate(self, project_id, token):
        return project_id == "demo" and token == TOKEN

    def read_revision(self, project_id, revision=None):
        return self.document if project_id == "demo" and revision in {None, 1} else None

    def ingest(self, event, enqueue):
        if event["wa_id"] == "unknown":
            raise UnknownParticipant()
        key = event["message_id"]
        inserted = key not in self.inputs
        self.inputs[key] = event
        if inserted:
            enqueue(None, "demo")
        return {"inserted": inserted}

    def record_delivery(self, *args):
        if args[2] not in {"sent", "delivered", "read", "failed"}:
            raise ValueError("Unsupported delivery status")
        self.deliveries.append(args)


@pytest.fixture
def api():
    repository = MemoryRepository()
    queue = []
    app = create_app(Settings(database_url="postgresql://not-used", meta_app_secret=SECRET,
                             meta_verify_token="synthetic-verify-token"),
                     repository=repository, enqueue=lambda conn, project: queue.append(project))
    with TestClient(app) as client:
        yield client, repository, queue


def payload(messages=None, statuses=None):
    return {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages",
        "value": {"metadata": {"phone_number_id": "phone-01"}, "messages": messages or [], "statuses": statuses or []}}]}]}


def message(identifier="wamid.synthetic-01", **changes):
    return {"id": identifier, "from": "synthetic-participant", "timestamp": "1795734000",
            "type": "text", "text": {"body": "Nossa operação usa um TMS."}, **changes}


def signed_post(client, data):
    raw = json.dumps(data).encode()
    signature = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return client.post("/webhooks/whatsapp", content=raw,
        headers={"X-Hub-Signature-256": signature, "Content-Type": "application/json"})


def test_read_authentication_and_project_isolation(api):
    client, _, _ = api
    path = "/v1/projects/demo/context/revisions/1/summary"
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get(path.replace("demo", "other"), headers={"Authorization": "Bearer " + TOKEN}).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer " + TOKEN}).status_code == 200


def test_four_views_share_identity_and_evidence_links(api):
    client, repository, _ = api
    headers = {"Authorization": "Bearer " + TOKEN}
    prefix = "/v1/projects/demo/context/revisions/1"
    eid = repository.document["evidence"][0]["id"]
    views = [client.get(prefix + suffix, headers=headers).json()
             for suffix in ("/summary", "/topics/frete", "/evidence/" + eid, "/export")]
    assert all(view["project_id"] == "demo" and view["revision"] == 1 for view in views)
    assert views[2]["evidence"]["quote"] == "usa peso"
    assert views[1]["claims"][0]["id"] in views[2]["claim_ids"]
    assert views[0]["blockers"] and views[1]["blockers"]
    assert "evidence" not in views[0] and "evidence" not in views[1]
    assert client.get(prefix.replace("/1", "/2") + "/export", headers=headers).status_code == 404
    assert client.get(prefix + "/topics/missing", headers=headers).status_code == 404
    assert client.get(prefix + "/evidence/missing", headers=headers).status_code == 404
    assert client.get(prefix.replace("/1", "/0") + "/summary", headers=headers).status_code == 422


def test_hmac_raw_body_and_batched_deduplication(api):
    client, repository, queue = api
    batch = payload([message(), message("wamid.synthetic-02")])
    first = signed_post(client, batch)
    assert first.status_code == 200 and first.json()["accepted"] == 2
    assert signed_post(client, batch).json()["duplicates"] == 2
    assert len(repository.inputs) == 2 and len(queue) == 2
    assert client.post("/webhooks/whatsapp", json=batch).status_code == 403
    assert client.post("/webhooks/whatsapp", content=b"{}",
                       headers={"X-Hub-Signature-256": "sha256=" + "0" * 64}).status_code == 403


def test_unknown_participant_and_unsupported_type_do_not_become_facts(api):
    client, repository, queue = api
    result = signed_post(client, payload([message(**{"from": "unknown"}), message("image", type="image")]))
    assert result.status_code == 200
    assert result.json()["unknown"] == 1 and result.json()["unsupported"] == 1
    assert not repository.inputs and not queue


def test_malformed_signed_payload_is_rejected_before_ack(api):
    client, _, _ = api
    assert signed_post(client, {"object": "whatsapp_business_account", "entry": "bad"}).status_code == 400


def test_webhook_limits_and_challenge(api):
    client, _, _ = api
    assert client.post("/webhooks/whatsapp", content=b"x" * (1024 * 1024 + 1)).status_code == 413
    assert client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe",
        "hub.verify_token": "synthetic-verify-token", "hub.challenge": "123456"}).text == "123456"
    assert client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe",
        "hub.verify_token": "wrong", "hub.challenge": "123456"}).status_code == 403


def test_deleted_callback_does_not_break_signed_batch(api):
    client, _, _ = api
    result = signed_post(client, payload([message()], [{"id": "out.synthetic-01", "status": "deleted",
        "timestamp": "1795734000", "recipient_id": "synthetic-participant"}]))
    assert result.status_code == 200 and result.json()["accepted"] == 1
