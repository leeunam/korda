"""Operator boundaries and provider failures, including immutable transcript correction."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest

from korda_context.cli import snapshot
from korda_context.config import Settings
from korda_context.llm import JsonModel, ModelError, TransientModelError


def test_provider_configuration_does_not_silently_enable_real_calls():
    settings = Settings(database_url="postgresql://synthetic@localhost/synthetic")
    with pytest.raises(ValueError, match="desativados"):
        settings.check_providers()
    with pytest.raises(ValueError, match="HTTPS"):
        Settings(database_url="postgresql://synthetic@localhost/synthetic", llm_url="http://insecure.test")
    assert "synthetic@" not in repr(settings)


def test_json_model_rejects_partial_output_and_clears_previous_usage():
    responses = [httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true}'}}],
                                             "usage": {"prompt_tokens": 12}}),
                 httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {"content": '{}'}}]})]
    model = JsonModel(api_key="synthetic", base_url="https://gateway.test", model="explicit-model",
                     client=httpx.Client(transport=httpx.MockTransport(lambda _: responses.pop(0))))
    assert model("system", "data") == {"ok": True}
    assert model.last_usage["usage"]["prompt_tokens"] == 12
    with pytest.raises(ModelError, match="incompleta"):
        model("system", "data")
    assert model.last_usage == {}


@pytest.mark.skipif(not os.environ.get("CONTEXT_TEST_DATABASE_URL"), reason="real PostgreSQL required")
def test_transcript_correction_is_new_input_and_keeps_original_history():
    # Reuse only infrastructure, not expected domain answers, from the PG tests.
    from test_persistence import repo as repo_fixture, event
    fixture = repo_fixture.__wrapped__()
    repository = next(fixture)
    try:
        original = repository.ingest(event("audio-original", kind="audio", text=None,
                                           media_id="media-synthetic", mime_type="audio/ogg"), lambda *_: None)
        with repository.transaction("demo") as session:
            first = session.add_transcription(original["id"], "ocupação por peso", "nova-3")
            context = snapshot(session)
            session.mark_input(original["id"], "processed")
            queued = []
            corrected = session.correct_transcript(original["id"], "ocupação por volume", "palavra incorreta",
                                                     lambda conn, project: queued.append(project))
            assert corrected["id"] != original["id"] and queued == ["demo"]
            assert session.get_input(original["id"])["status"] == "processed"
            assert session.get_transcription(corrected["id"])["version"] == 2
            assert session.get_transcription(corrected["id"])["text"] == "ocupação por volume"
            stored = session.conn.execute("SELECT * FROM ctx_transcriptions WHERE input_id=%s ORDER BY version",
                                           (original["id"],)).fetchall()
            assert [t["text"] for t in stored] == ["ocupação por peso", "ocupação por volume"]
            assert stored[0]["id"] == first["id"]
        assert repository.read_revision("demo", context["revision"]) == context
        with pytest.raises(ValueError, match="project_id"):
            repository.create_project("../escape", "Synthetic", "newphone", "x" * 32, {})
    finally:
        fixture.close()


@pytest.mark.skipif(not os.environ.get("CONTEXT_TEST_DATABASE_URL"), reason="real PostgreSQL required")
def test_immutable_reads_do_not_wait_for_a_model_holding_the_writer_lock():
    from test_persistence import repo as repo_fixture
    fixture = repo_fixture.__wrapped__()
    repository = next(fixture)
    entered, release = Event(), Event()
    try:
        with repository.transaction("demo") as session:
            initial = snapshot(session)
        def writer():
            with repository.transaction("demo") as session:
                snapshot(session)
                entered.set()
                assert release.wait(5)
        with ThreadPoolExecutor(max_workers=2) as pool:
            writing = pool.submit(writer)
            assert entered.wait(5)
            try:
                assert pool.submit(repository.read_revision, "demo").result(timeout=2) == initial
            finally:
                release.set()
            writing.result(timeout=5)
        assert repository.read_revision("demo")["revision"] == initial["revision"] + 1
    finally:
        release.set()
        fixture.close()
