"""Acceptance of the composed pipeline with PostgreSQL and deterministic providers.

These tests demonstrate plumbing, history and failure handling, not LLM quality.
"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from korda_context.channel import AmbiguousSendError, PermanentChannelError, TransientChannelError
from korda_context.config import Settings
from korda_context.domain import new_context
from korda_context.llm import TransientModelError
from korda_context.persistence import Repository
from korda_context.worker import Pipeline, make_queue
from test_persistence import repo, DATABASE_URL


pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="Real PostgreSQL is required")


class Model:
    model = "synthetic-organizer"

    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = 0

    def __call__(self, system, data):
        self.calls += 1
        body = json.loads(data)
        if not self.steps:
            raise AssertionError("Unexpected extra model call")
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        result = step(body) if callable(step) else step
        return {"base_revision": body["context"]["revision"], **result}


class Channel:
    def __init__(self, failure=None):
        self.sent = []
        self.failure = failure
        self.downloads = 0

    def send_text(self, phone, participant, text):
        self.sent.append((phone, participant, text))
        if self.failure:
            raise self.failure
        return "out.synthetic-" + str(len(self.sent))

    def download_audio(self, phone, media_id, directory):
        self.downloads += 1
        return {"path": Path("/private/synthetic.ogg"), "sha256": "a" * 64,
                "mime_type": "audio/ogg", "size_bytes": 100}


class Transcriber:
    def __init__(self, failure=None):
        self.calls = 0
        self.failure = failure

    def transcribe(self, path, mime):
        self.calls += 1
        if self.failure:
            raise self.failure
        return {"text": "O rateio usa peso bruto.", "model": "fake-stt", "model_version": "fake-stt-v1", "words": []}


def event(identifier="wamid.synthetic-01", *, text="O rateio usa peso bruto.", wa_id="synthetic-finance", **changes):
    return {"phone_number_id": "phone-01", "message_id": identifier, "wa_id": wa_id,
        "timestamp": datetime.now(timezone.utc), "kind": "text", "text": text, **changes}


def declare(body):
    return {"claims": [{"ref": "rateio", "topic": "frete", "key": "rateio", "kind": "rule",
        "statement": "O rateio usa peso bruto", "value": "peso_bruto", "quote": body["current_text"]}]}


def confirm(body):
    return {"confirm_claim_ids": body["pending_confirmation_ids"]}


def enqueue(conn, project_id, delay=0):
    # Marker transactionally persists scheduling requests; the real queue has its own test.
    conn.execute("INSERT INTO ctx_model_usage(project_id,model,usage,latency_ms) VALUES (%s,'fake-queue',%s,0)",
                 (project_id, json.dumps({"delay": delay})))


@pytest.fixture
def build(repo, monkeypatch):
    def question(self, session, participant, context):
        claims = [c for c in context.claims if c.state == "declarada" and
                  context.required_topics.get(c.topic) == participant["role"]]
        session.create_outbox(participant["id"], context.revision,
            "Confirma o uso do peso bruto?" if claims else "Qual é o próximo processo?",
            {"claim_ids": [claims[0].id] if claims else [], "topic": "frete"},
            dedupe_key=f"question:{context.revision}:{participant['id']}")
    monkeypatch.setattr(Pipeline, "_question", question)

    def create(steps, *, channel=None, transcriber=None):
        return Pipeline(Settings(database_url=repo.dsn, media_dir=Path("/private")), repo,
            channel or Channel(), transcriber or Transcriber(), Model(steps), Model([]), enqueue)
    return create


def test_two_rounds_confirmation_dedup_and_restart(repo, build):
    pipeline = build([declare, confirm])
    first = repo.ingest(event(), enqueue)
    assert not repo.ingest(event(), enqueue)["inserted"]
    pipeline.process("demo")
    initial = repo.read_revision("demo", 1)
    assert initial["state"] == "rascunho" and initial["claims"][0]["state"] == "declarada"
    repo.ingest(event("wamid.synthetic-02", text="Sim"), enqueue)
    pipeline.repository = Repository(repo.dsn)
    pipeline.process("demo")
    confirmed = repo.read_revision("demo", 2)
    assert confirmed["state"] == "pronto" and confirmed["claims"][0]["state"] == "confirmada"
    assert confirmed["processed_input_ids"][0] == first["id"]
    assert confirmed["claims"][0]["confirmation"]["role"] == "financeiro"
    assert repo.read_revision("demo", 1) == initial
    before = pipeline.organizer_model.calls
    pipeline.process("demo")
    assert pipeline.organizer_model.calls == before


def test_audio_evidence_keeps_original_and_transcription_version(repo, build):
    pipeline = build([declare])
    received = repo.ingest(event(kind="audio", text=None, media_id="media-01", mime_type="audio/ogg"), enqueue)
    pipeline.process("demo")
    document = repo.read_revision("demo")
    evidence = document["evidence"][0]
    assert evidence["kind"] == "audio_transcript" and evidence["transcription_version"] == 1
    assert evidence["source_id"] == "wamid.synthetic-01" and evidence["quote"] == "O rateio usa peso bruto."
    with repo.transaction("demo") as session:
        assert session.get_input(received["id"])["original_text"] is None
        assert session.get_transcription(received["id"])["model"] == "fake-stt-v1"
    pipeline.process("demo")
    assert pipeline.transcriber.calls == 1


def test_real_interviewer_routes_two_areas_to_one_phone(repo):
    topics = {"processo": "operacao", "frete_rateio": "financeiro"}
    repo.create_project("combined", "Empresa sintética", "phone-02", "synthetic-test-token-with-32-characters", topics)
    participant = repo.add_participant("combined", "synthetic-combined", "Responsável sintético", ["operacao", "financeiro"])

    def both(body):
        assert body["participant"]["roles"] == ["operacao", "financeiro"]
        return {"claims": [{"ref": topic, "topic": topic, "key": "regra", "kind": "rule",
                            "statement": body["current_text"], "quote": body["current_text"], "value": value}
                           for topic, value in (("processo", "TMS"), ("frete_rateio", "peso"))]}

    channel = Channel()
    pipeline = Pipeline(Settings(database_url=repo.dsn), repo, channel, Transcriber(),
                        Model([both, confirm, confirm]), Model([]), enqueue)
    for index, text in enumerate(("Usamos TMS e rateio por peso.", "Confirmo", "Confirmo")):
        repo.ingest(event(f"wamid.combined-{index}", text=text, phone_number_id="phone-02", wa_id="synthetic-combined"), enqueue)
        pipeline.process("combined")
    context = repo.read_revision("combined")
    assert context["state"] == "pronto"
    assert {c["topic"]: c["confirmation"]["role"] for c in context["claims"]} == topics
    assert {c["confirmation"]["participant_id"] for c in context["claims"]} == {participant["id"]}
    assert {message[1] for message in channel.sent} == {"synthetic-combined"}


def test_failed_audio_blocks_later_text_until_explicit_resolution(repo, build):
    pipeline = build([declare], transcriber=Transcriber(TransientChannelError("stt_unavailable")))
    audio = repo.ingest(event(kind="audio", text=None, media_id="media-01"), enqueue)
    text = repo.ingest(event("wamid.synthetic-02"), enqueue)
    for _ in range(3):
        pipeline.process("demo")
    with repo.transaction("demo") as session:
        failed = session.next_input()
        assert failed["id"] == audio["id"] and failed["status"] == "failed" and failed["attempts"] == 3
        assert session.get_input(text["id"])["status"] == "pending"
        session.resolve_input(audio["id"], "Operator requested replacement as text")
    assert pipeline.channel.sent and "três tentativas" in pipeline.channel.sent[-1][2]
    pipeline.process("demo")
    assert repo.read_revision("demo")["processed_input_ids"] == [text["id"]]


def test_transcription_is_not_repeated_after_transient_organizer_failure(repo, build):
    pipeline = build([TransientModelError("temporarily unavailable"), declare])
    received = repo.ingest(event(kind="audio", text=None, media_id="media-01"), enqueue)
    pipeline.process("demo")
    with repo.transaction("demo") as session:
        assert session.get_transcription(received["id"])["version"] == 1
        assert session.get_input(received["id"])["status"] == "pending"
    pipeline.process("demo")
    assert pipeline.transcriber.calls == 1 and pipeline.organizer_model.calls == 2


def test_uncertain_send_is_not_retried_after_restart(repo, build):
    pipeline = build([declare], channel=Channel(AmbiguousSendError("timeout_after_write")))
    repo.ingest(event(), enqueue)
    pipeline.process("demo")
    with repo.transaction("demo") as session:
        row = session.conn.execute("SELECT * FROM ctx_outbox WHERE project_id='demo'").fetchone()
        assert row["state"] == "uncertain" and row["attempts"] == 1
    pipeline.repository = Repository(repo.dsn)
    pipeline.process("demo")
    assert len(pipeline.channel.sent) == 1


def test_service_window_waits_for_customer_instead_of_sending_template(repo, build):
    pipeline = build([])
    participant = repo.get_participant("phone-01", "synthetic-finance")
    with repo.transaction("demo") as session:
        out = session.create_outbox(participant["id"], 0, "Precisamos esclarecer o rateio.", kind="notice")
    pipeline.send_pending("demo")
    with repo.transaction("demo") as session:
        assert session.get_outbox(out["id"])["state"] == "waiting_window"
    assert pipeline.channel.sent == []
    repo.ingest(event(), enqueue)
    pipeline.send_pending("demo")
    assert len(pipeline.channel.sent) == 1


def test_stale_question_is_cancelled_and_regenerated_from_current_revision(repo, build):
    pipeline = build([declare])
    participant = repo.get_participant("phone-01", "synthetic-finance")
    with repo.transaction("demo") as session:
        old = session.create_outbox(participant["id"], 0, "OLD QUESTION")
    repo.ingest(event(), enqueue)
    pipeline.process("demo")
    with repo.transaction("demo") as session:
        assert session.get_outbox(old["id"])["state"] == "cancelled"
    assert all(body != "OLD QUESTION" for _, _, body in pipeline.channel.sent)
    assert len(pipeline.channel.sent) == 1


def test_pause_and_resume_preserve_pending_inputs(repo, build):
    pipeline = build([declare])
    received = repo.ingest(event(), enqueue)
    with repo.transaction("demo") as session:
        session.set_interview_state("paused")
    pipeline.process("demo")
    assert pipeline.organizer_model.calls == 0
    with repo.transaction("demo") as session:
        assert session.next_input()["id"] == received["id"]
        session.set_interview_state("active")
    pipeline.process("demo")
    assert repo.read_revision("demo")["processed_input_ids"] == [received["id"]]


def test_explicit_correction_preserves_old_rule_and_requires_new_confirmation(repo, build):
    def correction(body):
        old = body["context"]["claims"][0]["id"]
        return {"claims": [{"ref": "new", "topic": "frete", "key": "rateio", "kind": "rule",
            "statement": "O rateio usa volumes", "value": "volumes", "quote": body["current_text"], "replaces_claim_id": old}]}
    pipeline = build([declare, confirm, correction, confirm])
    for index, text in enumerate(("O rateio usa peso bruto.", "Sim", "Corrigindo: o rateio usa volumes.", "Confirmo"), 1):
        repo.ingest(event(f"wamid.synthetic-{index}", text=text), enqueue)
        pipeline.process("demo")
    latest = repo.read_revision("demo")
    assert latest["revision"] == 4
    assert latest["claims"][0]["state"] == "substituida"
    assert latest["claims"][1]["value"] == "volumes" and latest["claims"][1]["state"] == "confirmada"
    assert repo.read_revision("demo", 2)["claims"][0]["value"] == "peso_bruto"


def test_fabricated_quote_fails_without_persisting_facts(repo, build):
    def fabricate(body):
        proposal = declare(body)
        proposal["claims"][0]["quote"] = "This sentence never occurred"
        return proposal
    pipeline = build([fabricate])
    received = repo.ingest(event(), enqueue)
    pipeline.process("demo")
    assert repo.read_revision("demo") is None
    with repo.transaction("demo") as session:
        assert session.get_input(received["id"])["status"] == "failed"
        assert session.project()["model_calls"] == 1


def test_real_procrastinate_enqueue_uses_receipt_transaction(repo):
    app, real_enqueue = make_queue(Settings(database_url=repo.dsn))
    with repo.connect() as connection:
        connection.execute(app.schema_manager.get_schema())
    received = repo.ingest(event(), real_enqueue)
    with repo.connect() as connection:
        job = connection.execute("SELECT * FROM procrastinate_jobs").fetchone()
        assert job["task_name"] == "context.process" and job["args"] == {"project_id": "demo"}
        assert job["lock"] == "context:demo"
    assert not repo.ingest(event(), real_enqueue)["inserted"]
    with repo.connect() as connection:
        assert connection.execute("SELECT COUNT(*) AS n FROM procrastinate_jobs").fetchone()["n"] == 1

    def fail_after_enqueue(connection, project_id):
        real_enqueue(connection, project_id)
        raise RuntimeError("synthetic failure after durable enqueue")
    with pytest.raises(RuntimeError, match="after durable enqueue"):
        repo.ingest(event("wamid.rollback"), fail_after_enqueue)
    with repo.connect() as connection:
        assert connection.execute("SELECT COUNT(*) AS n FROM procrastinate_jobs").fetchone()["n"] == 1
        assert connection.execute("SELECT COUNT(*) AS n FROM ctx_inbox").fetchone()["n"] == 1
