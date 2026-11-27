"""Integration tests against an explicitly supplied, disposable PostgreSQL DB.

Each test owns a uniquely named schema; no existing application tables are touched.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest
from sqlalchemy import create_engine

from korda_context.persistence import NotFound, Repository, StaleRevision, UnknownParticipant


DATABASE_URL = os.environ.get("CONTEXT_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="CONTEXT_TEST_DATABASE_URL is required (real PostgreSQL)")
SERVICE = Path(__file__).resolve().parents[1]
TOKEN = "synthetic-test-token-with-32-characters"
NOW = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def repo():
    schema = "ctx_test_" + uuid4().hex
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(DATABASE_URL, options=f"-csearch_path={schema},public")
    engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(dsn))
    config = Config(str(SERVICE / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    engine.dispose()
    repository = Repository(dsn)
    repository.create_project("demo", "Transportadora sintética", "phone-01", TOKEN, {"frete": "financeiro"})
    repository.add_participant("demo", "synthetic-operations", "Operação fictícia", "operacao")
    repository.add_participant("demo", "synthetic-finance", "Financeiro fictício", "financeiro")
    try:
        yield repository
    finally:
        with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def event(message_id="wamid.synthetic-01", **changes):
    return {"phone_number_id": "phone-01", "message_id": message_id,
            "wa_id": "synthetic-operations", "timestamp": NOW, "kind": "text",
            "text": "Nossa operação usa um TMS.", **changes}


def enqueue_marker(conn, project_id):
    # The injected callback is deliberately SQL on the same connection.
    conn.execute("INSERT INTO ctx_model_usage(project_id,model,usage,latency_ms) VALUES (%s,'queue-marker','{}',0)",
                 (project_id,))


def test_ingest_is_atomic_idempotent_and_preserves_equal_distinct_messages(repo):
    first = repo.ingest(event(), enqueue_marker)
    repeated = repo.ingest(event(), enqueue_marker)
    second = repo.ingest(event("wamid.synthetic-02"), enqueue_marker)
    assert first["inserted"] and not repeated["inserted"] and second["inserted"]
    assert first["id"] == repeated["id"] != second["id"]
    with repo.transaction("demo") as session:
        assert session.pending_inputs() == [first["id"], second["id"]]
        assert len(session.model_usage()) == 2
    assert Repository(repo.dsn).read_revision("demo") is None


def test_enqueue_failure_rolls_back_receipt_and_customer_window(repo):
    def broken(conn, project_id):
        enqueue_marker(conn, project_id)
        raise RuntimeError("synthetic queue failure")

    with pytest.raises(RuntimeError, match="synthetic queue failure"):
        repo.ingest(event(), broken)
    with repo.transaction("demo") as session:
        assert session.pending_inputs() == []
        assert session.model_usage() == []
        assert all(p["last_customer_at"] is None for p in session.participants())


def test_registration_and_project_authentication(repo):
    assert repo.authenticate("demo", TOKEN)
    assert not repo.authenticate("demo", "wrong")
    assert not repo.authenticate("missing", TOKEN)
    assert repo.get_participant("phone-01", "synthetic-finance")["role"] == "financeiro"
    with pytest.raises(UnknownParticipant):
        repo.ingest(event(wa_id="unregistered"), enqueue_marker)
    with pytest.raises(NotFound):
        repo.get_project("missing")


def test_one_phone_can_have_multiple_enrolled_roles_without_duplicate_identity(repo):
    participant = repo.add_participant("demo", "synthetic-combined", "Responsável sintético",
                                       ["operacao", "financeiro", "operacao"])
    loaded = repo.get_participant("phone-01", "synthetic-combined")
    assert loaded["id"] == participant["id"]
    assert loaded["roles"] == ["operacao", "financeiro"]
    assert loaded["role"] == "operacao"
    assert repo.get_participant("phone-01", "synthetic-finance")["roles"] == ["financeiro"]
    with repo.transaction("demo") as session:
        assert sum(p["wa_id"] == "synthetic-combined" for p in session.participants()) == 1
    for invalid in ([], [""], ["operacao", None]):
        with pytest.raises(ValueError, match="roles"):
            repo.add_participant("demo", "invalid", "Inválido", invalid)


def test_roles_migration_preserves_existing_participant_and_history():
    schema = "ctx_test_" + uuid4().hex
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(DATABASE_URL, options=f"-csearch_path={schema},public")
    engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(dsn))
    config = Config(str(SERVICE / "alembic.ini"))
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "context_0001")
        with psycopg.connect(dsn) as conn:
            conn.execute("INSERT INTO ctx_projects(id,name,phone_number_id,token_hash) VALUES ('demo','Sintética','phone','hash')")
            conn.execute("INSERT INTO ctx_participants(id,project_id,wa_id,name,role) VALUES ('existing','demo','synthetic','Responsável','financeiro')")
            conn.execute("INSERT INTO ctx_revisions(project_id,revision,document) VALUES ('demo',1,'{\"preserved\":true}')")
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        with psycopg.connect(dsn, row_factory=psycopg.rows.dict_row) as conn:
            row = conn.execute("SELECT * FROM ctx_participants").fetchone()
            assert row["id"] == "existing" and row["roles"] == ["financeiro"]
            assert conn.execute("SELECT document FROM ctx_revisions").fetchone()["document"] == {"preserved": True}
    finally:
        engine.dispose()
        with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_failed_audio_cannot_be_overtaken_and_resolution_is_explicit(repo):
    audio = repo.ingest(event(kind="audio", text=None, media_id="media-01", mime_type="audio/ogg"), enqueue_marker)
    text = repo.ingest(event("wamid.synthetic-02"), enqueue_marker)
    with repo.transaction("demo") as session:
        for attempt in range(3):
            session.mark_input(audio["id"], "processing", increase_attempts=True)
        session.mark_input(audio["id"], "failed", error="synthetic transcription failure")
        assert session.next_input()["id"] == audio["id"]
        with pytest.raises(ValueError, match="retry limit"):
            session.mark_input(audio["id"], "processing", increase_attempts=True)
        with pytest.raises(ValueError, match="earliest"):
            session.save_revision(0, {"project_id": "demo", "revision": 1}, text["id"])
        with pytest.raises(ValueError, match="reason"):
            session.resolve_input(audio["id"], "")
        session.resolve_input(audio["id"], "Operator recorded the request to resend as text")
        assert session.next_input()["id"] == text["id"]


def test_transcriptions_are_versioned_and_original_evidence_is_immutable(repo):
    audio = repo.ingest(event(kind="audio", text=None, media_id="media-01"), enqueue_marker)
    with repo.transaction("demo") as session:
        media = session.add_media(audio["id"], "/private/synthetic.ogg", "a" * 64, "audio/ogg", 128)
        original = session.add_transcription(audio["id"], "cem", "fake-stt", media["id"])
        corrected = session.add_transcription(audio["id"], "sem", "operator-correction", media["id"], correction_reason="human correction")
        assert original["version"] == 1 and corrected["version"] == 2
        assert session.get_transcription(audio["id"])["text"] == "sem"
        assert session.get_input(audio["id"])["original_text"] is None
    with pytest.raises(psycopg.DatabaseError, match="append-only"):
        with repo.connect() as conn:
            conn.execute("UPDATE ctx_transcriptions SET text='fabricated' WHERE id=%s", (original["id"],))
    with pytest.raises(psycopg.DatabaseError, match="immutable"):
        with repo.connect() as conn:
            conn.execute("UPDATE ctx_inbox SET media_id='changed' WHERE id=%s", (audio["id"],))


def test_context_commit_checks_revision_and_preserves_previous_snapshot(repo):
    received = repo.ingest(event(), enqueue_marker)
    with repo.transaction("demo") as session:
        session.save_revision(0, {"project_id": "demo", "revision": 1, "facts": ["declared"]}, received["id"])
    with repo.transaction("demo") as session:
        with pytest.raises(StaleRevision):
            session.save_revision(0, {"project_id": "demo", "revision": 1})
        session.save_revision(1, {"project_id": "demo", "revision": 2, "facts": ["confirmed"]})
    assert repo.read_revision("demo", 1)["facts"] == ["declared"]
    assert repo.read_revision("demo")["facts"] == ["confirmed"]
    with pytest.raises(psycopg.DatabaseError, match="append-only"):
        with repo.connect() as conn:
            conn.execute("UPDATE ctx_revisions SET document='{}' WHERE project_id='demo' AND revision=1")


def test_project_lock_serializes_competing_context_updates(repo):
    def update():
        try:
            with repo.transaction("demo") as session:
                session.save_revision(0, {"project_id": "demo", "revision": 1})
                return "saved"
        except StaleRevision:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: update(), range(2))) == ["saved", "stale"]


def test_outbox_deduplication_restart_and_no_automatic_uncertain_resend(repo):
    participant = repo.get_participant("phone-01", "synthetic-operations")
    with repo.transaction("demo") as session:
        first = session.create_outbox(participant["id"], 0, "Qual sistema?", dedupe_key="question-01")
        repeated = session.create_outbox(participant["id"], 0, "Qual sistema?", dedupe_key="question-01")
        assert first["id"] == repeated["id"]
        session.set_outbox_state(first["id"], "sending", increase_attempts=True)
    assert repo.reconcile_sending("demo") == 1
    with repo.transaction("demo") as session:
        assert session.get_outbox(first["id"])["state"] == "uncertain"
        assert session.next_outbox() is None
        with pytest.raises(ValueError, match="uncertain"):
            session.set_outbox_state(first["id"], "pending")


def test_callbacks_can_arrive_before_ack_and_out_of_order(repo):
    participant = repo.get_participant("phone-01", "synthetic-operations")
    assert repo.record_delivery("phone-01", "out.synthetic-01", "read", NOW)
    assert not repo.record_delivery("phone-01", "out.synthetic-01", "read", NOW)
    with repo.transaction("demo") as session:
        row = session.create_outbox(participant["id"], 0, "Qual sistema?")
        session.set_outbox_state(row["id"], "sending")
        session.set_outbox_state(row["id"], "sent", message_id="out.synthetic-01")
    assert repo.record_delivery("phone-01", "out.synthetic-01", "sent", NOW)
    with repo.transaction("demo") as session:
        assert session.get_outbox(row["id"])["delivery_status"] == "read"


def test_confirmation_is_bound_to_latest_sent_unconsumed_question(repo):
    participant = repo.get_participant("phone-01", "synthetic-operations")
    with repo.transaction("demo") as session:
        question = session.create_outbox(participant["id"], 0, "Confirma?", {"claim_ids": ["claim-01"]})
        assert session.latest_question(participant["id"]) is None
        session.set_outbox_state(question["id"], "sending")
        session.set_outbox_state(question["id"], "sent", message_id="out.synthetic-01")
        assert session.latest_question(participant["id"])["question_data"]["claim_ids"] == ["claim-01"]
    received = repo.ingest(event(), enqueue_marker)
    with repo.transaction("demo") as session:
        session.consume_question(question["id"], received["id"])
        assert session.latest_question(participant["id"]) is None


def test_model_quota_usage_and_interview_cutoff_survive_restart(repo):
    received = repo.ingest(event(), enqueue_marker)
    with repo.transaction("demo") as session:
        assert session.reserve_model_call(1)
        assert not session.reserve_model_call(1)
        session.record_model_usage("synthetic-model", {"input_tokens": 25, "output_tokens": 12, "cost_usd": 0.001}, 42)
        closed = session.set_interview_state("closed")
        assert closed["cutoff_sequence"] == received["received_sequence"]
    fresh = Repository(repo.dsn)
    assert fresh.get_project("demo")["model_calls"] == 1
    assert fresh.get_project("demo")["status"] == "closed"
    with fresh.transaction("demo") as session:
        assert session.model_usage()[-1]["usage"]["output_tokens"] == 12
        assert session.set_interview_state("active")["cutoff"] is None
