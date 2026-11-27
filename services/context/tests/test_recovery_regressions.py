"""Crash, delayed replies and durable retries against real PostgreSQL.

Providers are deterministic synthetic doubles. These tests do not measure LLM quality.
"""

from datetime import timedelta
from pathlib import Path

import pytest

from korda_context.cli import snapshot
from korda_context.config import Settings
from korda_context.llm import TransientModelError
from korda_context.worker import Pipeline, make_queue, recover_stalled_jobs, worker_lease
from test_persistence import DATABASE_URL, repo
from test_pipeline import Channel, Model, Transcriber, build, confirm, declare, enqueue, event


pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="Real PostgreSQL is required")


def install_queue(repository):
    app, schedule = make_queue(Settings(database_url=repository.dsn))
    with repository.connect() as connection:
        connection.execute(app.schema_manager.get_schema())
    return schedule


def register_worker(connection):
    return connection.execute("INSERT INTO procrastinate_workers DEFAULT VALUES RETURNING id").fetchone()["id"]


def fetch_context_job(connection, worker_id):
    row = connection.execute(
        "SELECT j.* FROM procrastinate_fetch_job_v2(ARRAY['context']::varchar[],%s) j",
        (worker_id,),
    ).fetchone()
    return row["id"] if row else None


def test_orphan_doing_job_is_recovered_and_releases_the_real_queue_lock(repo):
    schedule = install_queue(repo)
    repo.ingest(event(), schedule)
    with repo.connect() as connection:
        orphan = connection.execute("SELECT id FROM procrastinate_jobs").fetchone()["id"]
        connection.execute("UPDATE procrastinate_jobs SET status='doing',worker_id=NULL WHERE id=%s", (orphan,))
        schedule(connection, "demo")
        worker_id = register_worker(connection)
        assert fetch_context_job(connection, worker_id) is None

    with worker_lease(repo) as connection:
        assert recover_stalled_jobs(connection) == 1

    with repo.connect() as connection:
        assert connection.execute("SELECT status FROM procrastinate_jobs WHERE id=%s", (orphan,)).fetchone()["status"] == "todo"
        assert fetch_context_job(connection, worker_id) == orphan
        # A recovered job is runnable, rather than merely appearing in a todo count.
        job = connection.execute("SELECT status,worker_id FROM procrastinate_jobs WHERE id=%s", (orphan,)).fetchone()
        assert job == {"status": "doing", "worker_id": worker_id}


def test_fresh_worker_heartbeat_prevents_stealing_a_doing_job(repo):
    schedule = install_queue(repo)
    repo.ingest(event(), schedule)
    with repo.connect() as connection:
        worker_id = register_worker(connection)
        job_id = fetch_context_job(connection, worker_id)
        assert job_id is not None

    with worker_lease(repo) as connection:
        with pytest.raises(RuntimeError, match="heartbeat"):
            recover_stalled_jobs(connection)

    with repo.connect() as connection:
        job = connection.execute("SELECT status,worker_id FROM procrastinate_jobs WHERE id=%s", (job_id,)).fetchone()
        assert job == {"status": "doing", "worker_id": worker_id}


def test_only_one_worker_lease_can_be_held_and_exit_releases_it(repo):
    with worker_lease(repo):
        with pytest.raises(RuntimeError, match="worker.*ativo"):
            with worker_lease(repo):
                pytest.fail("a second worker acquired the database lease")
    with worker_lease(repo) as connection:
        assert connection.execute("SELECT 1 AS ok").fetchone()["ok"] == 1


def test_delayed_yes_sent_before_the_question_does_not_consume_or_confirm(repo, build):
    pending_seen = []

    def inspect_pending(body):
        pending_seen.append(body["pending_confirmation_ids"])
        return confirm(body)

    pipeline = build([declare, inspect_pending])
    repo.ingest(event(), enqueue)
    pipeline.process("demo")
    participant = repo.get_participant("phone-01", "synthetic-finance")
    with repo.transaction("demo") as session:
        question = session.latest_question(participant["id"])
        assert question is not None

    delayed = repo.ingest(event("wamid.delayed-yes", text="Sim",
                                timestamp=question["sent_at"] - timedelta(seconds=5)), enqueue)
    assert delayed["received_at"] > question["sent_at"] > delayed["sent_at"]
    pipeline.process("demo")

    context = repo.read_revision("demo")
    assert pending_seen == [[]]
    assert context["claims"][0]["state"] == "declarada"
    assert context["claims"][0]["confirmation"] is None
    with repo.transaction("demo") as session:
        assert session.get_input(delayed["id"])["status"] == "processed"
        assert session.get_outbox(question["id"])["consumed_by_input_id"] is None
        with pytest.raises(ValueError, match="after the question"):
            session.consume_question(question["id"], delayed["id"])


def test_close_processes_backlog_but_post_cutoff_input_does_not_block_ready(repo, build):
    pipeline = build([declare, confirm])
    first = repo.ingest(event(), enqueue)
    pipeline.process("demo")
    confirmation = repo.ingest(event("wamid.before-cutoff", text="Sim"), enqueue)
    with repo.transaction("demo") as session:
        closed = session.set_interview_state("closed")
        snapshot(session)
        assert closed["cutoff_sequence"] == confirmation["received_sequence"]
        assert session.pending_inputs(closed["cutoff_sequence"]) == [confirmation["id"]]

    later = repo.ingest(event("wamid.after-cutoff", text="Informação adicional sintética."), enqueue)
    pipeline.process("demo")
    context = repo.read_revision("demo")
    assert context["state"] == "pronto" and context["interview_status"] == "encerrada"
    assert context["cutoff_sequence"] == confirmation["received_sequence"]
    assert context["pending_input_ids"] == []
    assert context["processed_input_ids"] == [first["id"], confirmation["id"]]
    assert context["claims"][0]["state"] == "confirmada"
    assert pipeline.organizer_model.calls == 2
    with repo.transaction("demo") as session:
        assert session.pending_inputs() == [later["id"]]
        assert session.pending_inputs(context["cutoff_sequence"]) == []
        assert session.get_input(later["id"])["status"] == "pending"


class QuestionModel:
    model = "synthetic-interviewer"

    def __init__(self, succeed_on_third):
        self.calls = 0
        self.succeed_on_third = succeed_on_third

    def __call__(self, system, data):
        self.calls += 1
        if self.calls > 3:
            raise AssertionError("interviewer retry limit was exceeded")
        if self.calls < 3 or not self.succeed_on_third:
            raise TransientModelError("synthetic temporary interviewer outage")
        return {"text": "Como o frete é dividido entre os pedidos?"}


@pytest.mark.parametrize("succeed_on_third", [False, True])
def test_interviewer_retries_are_durable_without_repeating_audio_or_organizer(repo, succeed_on_third):
    channel, transcriber = Channel(), Transcriber()
    organizer, interviewer = Model([{}]), QuestionModel(succeed_on_third)
    pipeline = Pipeline(Settings(database_url=repo.dsn, media_dir=Path("/private")), repo,
                        channel, transcriber, organizer, interviewer, enqueue)
    received = repo.ingest(event(kind="audio", text=None, media_id="media.synthetic-01",
                                mime_type="audio/ogg"), enqueue)

    for _ in range(4):
        pipeline.process("demo")

    assert organizer.calls == 1 and transcriber.calls == 1 and channel.downloads == 1
    assert interviewer.calls == 3
    assert len(channel.sent) == (1 if succeed_on_third else 0)
    with repo.transaction("demo") as session:
        stored = session.get_input(received["id"])
        assert stored["status"] == "processed" and stored["attempts"] == 1
        assert session.get_transcription(received["id"])["version"] == 1
        requests = session.conn.execute(
            "SELECT state,attempts FROM ctx_question_requests WHERE project_id='demo'"
        ).fetchall()
        assert requests == [{"state": "generated" if succeed_on_third else "failed", "attempts": 3}]
        assert session.project()["model_calls"] == 4
        scheduled = session.conn.execute(
            "SELECT usage FROM ctx_model_usage WHERE project_id='demo' AND model='fake-queue' ORDER BY id"
        ).fetchall()
        assert [row["usage"]["delay"] for row in scheduled] == [0, 10, 20]
