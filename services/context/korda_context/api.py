"""Webhook rápido e leitura autenticada de revisões imutáveis."""
from contextlib import asynccontextmanager
import hmac
import json

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

from .config import Settings
from .domain import ContextDocument
from .channel import PermanentChannelError, normalize_webhook, verify_signature
from .persistence import NotFound, Repository, UnknownParticipant
from . import retrieval


def create_app(settings: Settings | None = None, *, repository=None, enqueue=None) -> FastAPI:
    settings = settings or Settings.from_env()
    repository = repository or Repository(settings.database_url.get_secret_value())
    queue_holder = {}

    @asynccontextmanager
    async def lifespan(app):
        if enqueue is None:
            from .worker import make_queue
            queue_holder["queue"], queue_holder["enqueue"] = make_queue(settings)
            await queue_holder["queue"].open_async()
        try:
            yield
        finally:
            if "queue" in queue_holder:
                await queue_holder["queue"].close_async()

    app = FastAPI(title="Korda Context", version="0.2.0", lifespan=lifespan)
    bearer = HTTPBearer(auto_error=False)

    def authorize(project_id: str, credential: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if not credential or not repository.authenticate(project_id, credential.credentials):
            raise HTTPException(401, "Credencial de projeto inválida", headers={"WWW-Authenticate": "Bearer"})

    def document(project_id: str, revision: str) -> ContextDocument:
        try:
            number = None if revision == "latest" else int(revision)
            if number is not None and number < 1:
                raise ValueError()
        except ValueError:
            raise HTTPException(422, "Revisão deve ser positiva ou latest") from None
        try:
            result = repository.read_revision(project_id, number)
        except NotFound:
            result = None
        if result is None:
            raise HTTPException(404, "Revisão não encontrada")
        return ContextDocument.model_validate(result)

    @app.get("/healthz", include_in_schema=False)
    def health():
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    def ready():
        try:
            if repository.health():
                return {"status": "ready"}
        except Exception:
            pass
        raise HTTPException(503, "Persistência indisponível")

    @app.get("/webhooks/whatsapp", include_in_schema=False)
    def challenge(request: Request):
        query = request.query_params
        expected = settings.meta_verify_token.get_secret_value()
        supplied = query.get("hub.verify_token", "")
        if (not expected or query.get("hub.mode") != "subscribe"
                or not hmac.compare_digest(expected, supplied)):
            raise HTTPException(403, "Verificação recusada")
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(query.get("hub.challenge", ""))

    def receive(payload):
        try:
            normalized = normalize_webhook(payload)
        except (KeyError, ValueError, TypeError, PermanentChannelError):
            raise HTTPException(400, "Evento inválido") from None
        counts = {"accepted": 0, "duplicates": 0, "unknown": 0,
                  "unsupported": len(normalized["unsupported"])}
        for event in normalized["messages"]:
            try:
                item = repository.ingest(event, enqueue or queue_holder["enqueue"])
            except UnknownParticipant:
                counts["unknown"] += 1
                continue
            counts["accepted" if item["inserted"] else "duplicates"] += 1
        for status in normalized["statuses"]:
            if status["status"] not in {"sent", "delivered", "read", "failed"}:
                counts["unsupported"] += 1
                continue
            repository.record_delivery(status["phone_number_id"], status["message_id"],
                                       status["status"], status["timestamp"], status.get("error"))
        return counts

    @app.post("/webhooks/whatsapp", include_in_schema=False)
    async def webhook(request: Request):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 1024 * 1024:
                raise HTTPException(413, "Webhook excede limite de tamanho")
        secret = settings.meta_app_secret.get_secret_value()
        if not secret:
            raise HTTPException(503, "Webhook não configurado")
        if not verify_signature(bytes(body), request.headers.get("x-hub-signature-256"), secret):
            raise HTTPException(403, "Assinatura inválida")
        try:
            payload = json.loads(body)
        except ValueError:
            raise HTTPException(400, "JSON inválido") from None
        return await run_in_threadpool(receive, payload)

    prefix = "/v1/projects/{project_id}/context/revisions/{revision}"

    @app.get(prefix + "/summary", dependencies=[Depends(authorize)])
    def overview(project_id: str, revision: str):
        return retrieval.overview(document(project_id, revision))

    @app.get(prefix + "/topics/{topic_id}", dependencies=[Depends(authorize)])
    def topic(project_id: str, revision: str, topic_id: str):
        try:
            return retrieval.topic(document(project_id, revision), topic_id)
        except (KeyError, LookupError):
            raise HTTPException(404, "Tópico não encontrado") from None

    @app.get(prefix + "/evidence/{evidence_id}", dependencies=[Depends(authorize)])
    def evidence(project_id: str, revision: str, evidence_id: str):
        try:
            return retrieval.evidence(document(project_id, revision), evidence_id)
        except (KeyError, LookupError):
            raise HTTPException(404, "Evidência não encontrada") from None

    @app.get(prefix + "/export", response_model=ContextDocument, dependencies=[Depends(authorize)])
    def export(project_id: str, revision: str):
        return retrieval.export(document(project_id, revision))

    return app
