"""Operações administrativas locais; tokens são lidos do ambiente, nunca de argv."""
import argparse
import json
import os
from pathlib import Path
import sys

from alembic import command
from alembic.config import Config

from .config import Settings
from .domain import ContextDocument, new_context, ready
from .persistence import Repository
from .worker import make_queue

LOGISTICS_TOPICS = dict.fromkeys(("objetivo", "processo", "fontes", "restricoes",
    "frete_deduplicacao", "frete_cancelamento", "frete_elegibilidade", "otif_prazo",
    "otif_completude", "otif_data_ausente", "otif_sabado", "ocupacao_unidade", "ocupacao_agregacao"), "operacao")
LOGISTICS_TOPICS["frete_rateio"] = "financeiro"
SERVICE = Path(__file__).resolve().parents[1]


def migrate(settings):
    config = Config(str(SERVICE / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", settings.database_url.get_secret_value().replace("%", "%%"))
    command.upgrade(config, "head")
    app, _ = make_queue(settings)
    repo = Repository(settings.database_url.get_secret_value())
    with repo.connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(734108003)")
        if conn.execute("SELECT to_regclass('procrastinate_jobs') AS table_name").fetchone()["table_name"] is None:
            conn.execute(app.schema_manager.get_schema())


def snapshot(session):
    project = session.project()
    current = session.load_context()
    context = ContextDocument.model_validate(current) if current else new_context(project["id"], project["required_topics"])
    data = context.model_dump(mode="python")
    data.update(revision=context.revision + 1,
                interview_status={"active": "ativa", "paused": "pausada", "closed": "encerrada"}[project["status"]],
                pending_input_ids=session.pending_inputs(project["cutoff"]),
                cutoff_sequence=project["cutoff"], state="rascunho")
    context = ContextDocument.model_validate(data)
    if ready(context):
        context = context.model_copy(update={"state": "pronto"})
    return session.save_revision(context.revision - 1, context.model_dump(mode="json"))


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="action", required=True)
    commands.add_parser("migrate", help="Migra contexto e inicializa fila uma vez")
    project = commands.add_parser("project-create")
    project.add_argument("project_id")
    project.add_argument("--name", required=True)
    project.add_argument("--phone-number-id", required=True)
    project.add_argument("--token-env", default="CONTEXT_PROJECT_TOKEN")
    project.add_argument("--topics-json", type=Path, help="Mapa tópico→papel; padrão é roteiro logístico")
    participant = commands.add_parser("participant-add")
    participant.add_argument("project_id")
    participant.add_argument("--wa-id", required=True)
    participant.add_argument("--name", required=True)
    participant.add_argument("--role", required=True)
    for action in ("status", "pause", "resume", "close", "retry", "usage"):
        entry = commands.add_parser(action)
        entry.add_argument("project_id")
    resolve = commands.add_parser("resolve-input", help="Resolve explicitamente entrada que bloqueia processamento")
    resolve.add_argument("project_id")
    resolve.add_argument("input_id")
    resolve.add_argument("--reason", required=True)
    transcribe = commands.add_parser("correct-transcript", help="Preserva transcrição e cria nova entrada de correção")
    transcribe.add_argument("project_id")
    transcribe.add_argument("input_id")
    transcribe.add_argument("--text-file", type=Path, required=True)
    transcribe.add_argument("--reason", required=True)
    commands.add_parser("provider-check", help="Verifica configuração sem transmitir dados")
    commands.add_parser("model-smoke", help="Uma chamada JSON por modelo configurado; requer provedores reais")
    return root


def run(args, settings, repo):
    if args.action == "migrate":
        migrate(settings)
        return {"migrations": "applied"}
    if args.action == "provider-check":
        settings.check_providers()
        return {"configuration": "present", "network_tested": False}
    if args.action == "model-smoke":
        settings.check_providers()
        from .llm import JsonModel
        result = []
        for name in (settings.organizer_model, settings.interviewer_model):
            model = JsonModel(api_key=settings.llm_api_key.get_secret_value(), base_url=settings.llm_url,
                              model=name, max_tokens=128)
            if model('Retorne somente JSON {"ok":true}.', 'Verificação técnica sintética.') != {"ok": True}:
                raise ValueError("Modelo não satisfez o smoke test JSON")
            result.append(model.last_usage)
        return {"models": result}
    if args.action == "project-create":
        topics = json.loads(args.topics_json.read_text(encoding="utf-8")) if args.topics_json else LOGISTICS_TOPICS
        token = os.environ.get(args.token_env, "")
        repo.create_project(args.project_id, args.name, args.phone_number_id, token, topics)
        with repo.transaction(args.project_id) as session:
            snapshot(session)
        return {"project_id": args.project_id, "revision": 1}
    if args.action == "participant-add":
        participant = repo.add_participant(args.project_id, args.wa_id, args.name, args.role)
        return {"participant_id": participant["id"], "role": participant["role"]}
    if args.action == "usage":
        with repo.transaction(args.project_id) as session:
            return {"model_calls": session.project()["model_calls"], "usage": session.model_usage()}
    if args.action == "status":
        from .retrieval import overview
        with repo.transaction(args.project_id) as session:
            current = session.load_context()
            return {"project": session.project(), "context": overview(current) if current else None,
                    "pending_input_ids": session.pending_inputs(),
                    "question_requests": session.conn.execute(
                        "SELECT id,state,error,revision,attempts FROM ctx_question_requests WHERE project_id=%s ORDER BY created_at",
                        (args.project_id,)).fetchall(),
                    "outbox": session.conn.execute(
                        "SELECT id,state,error,revision,delivery_status FROM ctx_outbox WHERE project_id=%s ORDER BY created_at",
                        (args.project_id,)).fetchall()}
    app, enqueue = make_queue(settings)
    with app.open():
        with repo.transaction(args.project_id) as session:
            if args.action in {"pause", "resume", "close"}:
                session.set_interview_state({"pause": "paused", "resume": "active", "close": "closed"}[args.action])
                snapshot(session)
            elif args.action == "resolve-input":
                session.resolve_input(args.input_id, args.reason)
                snapshot(session)
            elif args.action == "correct-transcript":
                session.correct_transcript(args.input_id, args.text_file.read_text(encoding="utf-8"),
                                           args.reason, enqueue)
                snapshot(session)
                return {"project_id": args.project_id, "action": args.action, "scheduled": True}
            enqueue(session.conn, args.project_id)
    return {"project_id": args.project_id, "action": args.action, "scheduled": True}


def main(argv=None):
    args = parser().parse_args(argv)
    settings = Settings.from_env()
    repo = Repository(settings.database_url.get_secret_value())
    try:
        result = run(args, settings, repo)
    except (ValueError, LookupError) as exc:
        # Errors from these boundaries contain safe configuration/identity messages.
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, default=str, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
