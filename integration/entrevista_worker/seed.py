"""Registra uma entrevista sintética via webhook assinado em uma API local com Postgres."""

import argparse
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from .roteiro import DATA, TOPICOS, entrevistar, ler, modelo_sem_fatos, redator_de_pergunta


def requisicao(url, caminho, *, headers=None, body=None):
    base = urlsplit(url)
    if base.scheme != "http" or base.hostname not in {"127.0.0.1", "::1", "localhost"} or base.path not in ("", "/"):
        raise ValueError("a entrevista de teste requer uma API HTTP local")
    req = Request(url.rstrip("/") + caminho, data=body, headers=headers or {})
    with urlopen(req, timeout=15) as resposta:
        return json.load(resposta)


def exportar(url, projeto, revisao, token):
    caminho = f"/v1/projects/{quote(projeto, safe='')}/context/revisions/{int(revisao)}/export"
    return requisicao(url, caminho, headers={"Authorization": "Bearer " + token})


class CanalSintetico:
    """Confirma o envio da pergunta na outbox sem chamar o WhatsApp."""

    def __init__(self):
        self.numero = 0

    def send_text(self, _telefone, _participante, _pergunta):
        self.numero += 1
        return f"synthetic-out-{self.numero}"


def preparar(url, projeto, token):
    from korda_context.config import Settings
    from korda_context.persistence import Repository
    from korda_context.worker import Pipeline, make_queue

    settings = Settings.from_env()
    segredo = settings.meta_app_secret.get_secret_value()
    if not segredo or settings.real_providers:
        raise ValueError("configure CONTEXT_META_APP_SECRET de teste e desative CONTEXT_REAL_PROVIDERS")
    repo = Repository(settings.database_url.get_secret_value())
    formulario = ler(DATA / "inputs/formulario.json")
    telefone = "synthetic-" + projeto
    repo.create_project(projeto, formulario["company_name"], telefone, token, TOPICOS)
    participantes = {p["id"]: repo.add_participant(projeto, p["id"], p["name"], p["role"])
                     for p in formulario["participants"]}
    fila, enqueue = make_queue(settings)
    pipeline = Pipeline(settings, repo, CanalSintetico(), None, modelo_sem_fatos, redator_de_pergunta, enqueue)
    sequencia = 0

    def enviar(papel, texto):
        nonlocal sequencia
        sequencia += 1
        # O timestamp da Meta tem precisão de segundos. A resposta precisa chegar
        # depois da pergunta efetivamente marcada como enviada pelo PostgreSQL.
        proximo_segundo = int(time.time()) + 1
        time.sleep(max(0, proximo_segundo - time.time()) + 0.02)
        mensagem = {
            "id": f"wamid.synthetic-{projeto}-{sequencia}", "from": papel,
            "type": "text", "text": {"body": texto}, "timestamp": str(int(time.time())),
        }
        valor = {"metadata": {"phone_number_id": telefone}, "messages": [mensagem]}
        evento = {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": valor}]}]}
        corpo = json.dumps(evento, ensure_ascii=False).encode()
        headers = {"Content-Type": "application/json",
                   "X-Hub-Signature-256": "sha256=" + hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()}
        if sequencia == 1:
            try:
                requisicao(url, "/webhooks/whatsapp", headers={**headers, "X-Hub-Signature-256": "sha256=" + "0" * 64}, body=corpo)
            except HTTPError as exc:
                if exc.code != 403:
                    raise
            else:
                raise AssertionError("a API aceitou uma mensagem cuja assinatura não corresponde ao corpo")
        recebida = requisicao(url, "/webhooks/whatsapp", headers=headers, body=corpo)
        if recebida["accepted"] != 1:
            raise AssertionError(f"webhook não registrou o turno {sequencia}: {recebida}")
        pipeline.process(projeto)
        revisao = repo.read_revision(projeto)
        if not revisao or revisao["revision"] != sequencia:
            raise AssertionError(f"o produtor não persistiu a revisão {sequencia}")
        with repo.transaction(projeto) as sessao:
            pergunta = sessao.latest_question(participantes[papel]["id"])
        return revisao, pergunta["question_data"] if pergunta else {}

    with fila.open():
        pendente, pronta = entrevistar(enviar)
    if pendente["state"] != "rascunho" or pronta["state"] != "pronto":
        raise AssertionError("a entrevista precisa produzir rascunho e revisão pronta")
    for revisao in (pendente, pronta):
        if exportar(url, projeto, revisao["revision"], token) != revisao:
            raise AssertionError("a exportação autenticada da revisão diverge do documento persistido")
    return {"project_id": projeto, "pending_revision": pendente["revision"], "ready_revision": pronta["revision"], "url": url}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8091")
    parser.add_argument("--project", default="entrevista-01")
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    manifesto = preparar(args.url, args.project, os.environ["CONTEXT_PROJECT_TOKEN"])
    args.manifest.write_text(json.dumps(manifesto, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifesto))


if __name__ == "__main__":
    main()
