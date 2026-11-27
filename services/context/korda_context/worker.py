"""Durable project pipeline. Provider effects never run in the webhook."""
from datetime import datetime, timezone
from pathlib import Path
import logging

import procrastinate
from pydantic import ValidationError

from .channel import (AmbiguousSendError, DeepgramClient, MetaCloudClient,
                      PermanentChannelError, TransientChannelError, within_service_window)
from .config import Settings
from .domain import ContextDocument, new_context, ready
from .llm import JsonModel, ModelError, TransientModelError
from .organizer import Organizer
from .persistence import Repository

logger = logging.getLogger(__name__)
STATUS = {"active": "ativa", "paused": "pausada", "closed": "encerrada"}


class ProjectBudgetExceeded(ModelError):
    pass


class Pipeline:
    def __init__(self, settings, repository, channel, transcriber, organizer_model,
                 interviewer_model, enqueue):
        self.settings, self.repository = settings, repository
        self.channel, self.transcriber = channel, transcriber
        self.organizer_model, self.interviewer_model = organizer_model, interviewer_model
        self.enqueue = enqueue

    def _model(self, session, model):
        def generate(system, data):
            if not session.reserve_model_call(self.settings.max_llm_calls_per_project):
                raise ProjectBudgetExceeded("Cota de chamadas do projeto atingida")
            try:
                return model(system, data)
            finally:
                usage = getattr(model, "last_usage", {})
                if usage:
                    session.record_model_usage(usage["model"], usage.get("usage", {}), usage["latency_ms"])
        return generate

    def _context(self, session):
        project = session.project()
        doc = session.load_context()
        return ContextDocument.model_validate(doc) if doc else new_context(project["id"], project["required_topics"])

    def _question(self, session, participant, context):
        from .interview import Interviewer
        question = Interviewer(self._model(session, self.interviewer_model)).choose(context, participant)
        if question is None:
            return
        # The interviewer owns phrasing; the application stores the binding.
        session.create_outbox(participant["id"], context.revision, question.text,
            question_data={"claim_ids": question.claim_ids, "topic": question.topic},
            dedupe_key=f"question:{context.revision}:{participant['id']}")

    def _notice(self, session, row, message):
        session.create_outbox(row["participant_id"], session.project()["current_revision"], message,
                              kind="notice", dedupe_key="failure:" + row["id"])

    def process(self, project_id: str):
        """Procrastinate lock serializes jobs; DB lock also protects CLI writes."""
        for _ in range(100):
            stop = False
            with self.repository.transaction(project_id) as session:
                project = session.project()
                if project["status"] == "paused":
                    return
                row = session.next_input()
                if row is None:
                    break
                if project["status"] == "closed" and row["received_sequence"] > project["cutoff"]:
                    break
                if row["status"] == "failed":
                    self._notice(session, row, "Não consegui processar uma resposta anterior. "
                        "Peça ao operador para verificar a pendência antes de continuarmos.")
                    stop = True
                else:
                    participant = next(p for p in session.participants() if p["id"] == row["participant_id"])
                    row = session.mark_input(row["id"], "processing", increase_attempts=True)
                    try:
                        context = self._context(session)
                        text = row["resolved_text"] or row["original_text"]
                        transcription = None
                        if row["kind"] == "audio":
                            transcription = session.get_transcription(row["id"])
                            if transcription is None:
                                media = self.channel.download_audio(project["phone_number_id"], row["media_id"],
                                    self.settings.media_dir / project_id)
                                saved = session.add_media(row["id"], str(media["path"]), media["sha256"],
                                                          media["mime_type"], media["size_bytes"])
                                result = self.transcriber.transcribe(Path(media["path"]), media["mime_type"])
                                transcription = session.add_transcription(row["id"], result["text"],
                                    result.get("model_version") or result["model"], saved["id"], result.get("words", []))
                            text = transcription["text"]
                        challenge = session.latest_question(participant["id"])
                        if challenge and challenge["sent_at"] > row["received_at"]:
                            challenge = None
                        pending = challenge["question_data"].get("claim_ids", []) if challenge else []
                        new = Organizer(self._model(session, self.organizer_model)).organize(
                            context, row["id"], text, participant, project["required_topics"], pending,
                            input_kind=row["kind"], transcription_version=transcription["version"] if transcription else None,
                            source_id=row["message_id"], input_timestamp=row["sent_at"])
                        data = new.model_dump(mode="python")
                        data["pending_input_ids"] = [i for i in session.pending_inputs() if i != row["id"]]
                        data["interview_status"] = STATUS[project["status"]]
                        data["state"] = "rascunho"
                        new = ContextDocument.model_validate(data)
                        if ready(new):
                            new = new.model_copy(update={"state": "pronto"})
                        session.save_revision(context.revision, new.model_dump(mode="json"), row["id"])
                        if challenge:
                            session.consume_question(challenge["id"], row["id"])
                    except (TransientChannelError, TransientModelError) as exc:
                        retry = row["attempts"] < 3
                        session.mark_input(row["id"], "pending" if retry else "failed", error=type(exc).__name__)
                        if retry:
                            self.enqueue(session.conn, project_id, delay=10 * row["attempts"])
                        else:
                            self._notice(session, row, "Não consegui processar sua resposta após três tentativas. "
                                "Se enviou áudio, envie a informação por texto ou reenvie o áudio; "
                                "o operador precisa resolver a entrada pendente.")
                        stop = True
                    except (PermanentChannelError, ModelError, ValueError, ValidationError) as exc:
                        session.mark_input(row["id"], "failed", error=type(exc).__name__)
                        self._notice(session, row, "Não consegui validar sua resposta. "
                            "Envie a informação por texto ou peça ao operador para verificar a pendência.")
                        stop = True
                    else:
                        if not session.pending_inputs() and project["status"] == "active":
                            try:
                                self._question(session, participant, new)
                            except (ModelError, ValueError) as exc:
                                # Input is already committed logically; never organize it twice.
                                self._notice(session, row, "Sua resposta foi registrada. "
                                    "A próxima pergunta está aguardando revisão do operador.")
                                logger.warning("question_failed", extra={"project_id": project_id, "error_type": type(exc).__name__})
            if stop:
                break
        else:
            with self.repository.transaction(project_id) as session:
                self.enqueue(session.conn, project_id)
        self.send_pending(project_id)

    def send_pending(self, project_id):
        for _ in range(30):
            with self.repository.transaction(project_id) as session:
                project = session.project()
                if project["status"] == "paused":
                    return
                out = session.next_outbox()
                if out is None:
                    return
                if out["kind"] == "question":
                    if session.pending_inputs():
                        return
                    if project["status"] != "active":
                        session.set_outbox_state(out["id"], "cancelled", error="interview_closed")
                        continue
                    if out["revision"] != project["current_revision"]:
                        session.set_outbox_state(out["id"], "cancelled", error="stale_revision")
                        participant = next(p for p in session.participants() if p["id"] == out["participant_id"])
                        try:
                            self._question(session, participant, self._context(session))
                        except (ModelError, ValueError):
                            logger.warning("stale_question_regeneration_failed", extra={"project_id": project_id})
                        continue
                if not within_service_window(out["last_customer_at"]):
                    session.set_outbox_state(out["id"], "waiting_window")
                    continue
                if out["attempts"] >= 3:
                    session.set_outbox_state(out["id"], "failed", error="retry_limit")
                    continue
                session.set_outbox_state(out["id"], "sending", increase_attempts=True)
            # Sending is durably marked before the external side effect.
            try:
                message_id = self.channel.send_text(project["phone_number_id"], out["wa_id"], out["body"])
            except AmbiguousSendError:
                with self.repository.transaction(project_id) as session:
                    session.set_outbox_state(out["id"], "uncertain", error="ambiguous_send")
            except TransientChannelError:
                with self.repository.transaction(project_id) as session:
                    exhausted = out["attempts"] + 1 >= 3
                    session.set_outbox_state(out["id"], "failed" if exhausted else "pending", error="transient_send")
                    if not exhausted:
                        self.enqueue(session.conn, project_id, delay=10 * (out["attempts"] + 1))
                return
            except PermanentChannelError:
                with self.repository.transaction(project_id) as session:
                    session.set_outbox_state(out["id"], "failed", error="provider_rejected_send")
            else:
                with self.repository.transaction(project_id) as session:
                    session.set_outbox_state(out["id"], "sent", message_id=message_id)


def make_queue(settings: Settings):
    app = procrastinate.App(connector=procrastinate.PsycopgConnector(
        conninfo=settings.database_url.get_secret_value()))

    def enqueue(conn, project_id, delay=0):
        return process.configure(connection=conn, lock="context:" + project_id,
            schedule_in={"seconds": delay}).defer(project_id=project_id)

    @app.task(name="context.process", queue="context", retry=False)
    def process(project_id: str):
        settings.check_providers()
        pipeline = Pipeline(settings, Repository(settings.database_url.get_secret_value()),
            MetaCloudClient(settings.meta_access_token.get_secret_value(), settings.meta_graph_version),
            DeepgramClient(settings.deepgram_api_key.get_secret_value()),
            JsonModel(api_key=settings.llm_api_key.get_secret_value(), base_url=settings.llm_url,
                      model=settings.organizer_model, max_tokens=settings.max_output_tokens),
            JsonModel(api_key=settings.llm_api_key.get_secret_value(), base_url=settings.llm_url,
                      model=settings.interviewer_model, max_tokens=settings.max_output_tokens), enqueue)
        pipeline.process(project_id)

    return app, enqueue


def main():
    settings = Settings.from_env()
    settings.check_providers()
    repo = Repository(settings.database_url.get_secret_value())
    app, enqueue = make_queue(settings)
    with app.open():
        # On restart, never repeat sends that might already have reached Meta.
        for project_id in repo.list_project_ids():
            repo.reconcile_sending(project_id)
            with repo.transaction(project_id) as session:
                enqueue(session.conn, project_id)
        app.run_worker(queues=["context"], concurrency=3)


if __name__ == "__main__":
    main()
