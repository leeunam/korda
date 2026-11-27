"""Planejamento da construção: etapa do worker antes da aprovação 1.

Uma chamada à API da Feita transforma o plano base (gabarito do contexto) e o
contexto da descoberta no plano de construção. A própria LLM decide se há
contexto para construir:
- pronto: o documento entra no plano como `construction` (nova plan_version),
  e a pessoa aprova tudo junto na aprovação 1;
- falta contexto: as perguntas vão para `perguntas.json`, que volta para a
  descoberta; nenhum plano novo é gerado.
Nada é executado aqui: sem sandbox, sem fontes, sem dbt.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from services.planning.korda_planning import anexar_construcao, validar_plano
from services.planning.korda_planning.plano import contrato_contexto

from .documento_base import gerar_documento_base, remover_bloco_decisao
from .harness.cliente_chat import ClienteChatHttp
from .harness.config import ConfigHarness
from .harness.contexto import projetar_plano
from .harness.tipos import usd_para_centavos
from .worker import FalhaExecucao

MAX_TOKENS_PLANEJAMENTO = 8000


def validar_contexto(contexto: dict, plano: dict) -> None:
    """O planejamento precisa do contexto validado que originou o plano base."""
    contrato_contexto.validate_context(contexto)
    if (contexto["context_id"], contexto["revision"]) != (plano["context_id"], plano["context_revision"]):
        raise FalhaExecucao("o contexto informado não é a revisão que originou o plano")


def _gravar(caminho: Path, objeto) -> None:
    caminho.write_text(json.dumps(objeto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def planejar(plano: dict, contexto: dict, *, raiz: Path, cfg: ConfigHarness | None = None, cliente_llm=None) -> dict:
    """Gera a construção do plano ou as perguntas para a descoberta. Uma chamada de API.

    `cliente_llm` só existe para testes (executor `falso`).
    """
    cfg = cfg or ConfigHarness.de_ambiente()
    if cfg.executor not in ("chat", "falso"):
        raise FalhaExecucao("o planejamento usa a API da Feita: defina KORDA_EXECUTOR=chat")
    if cfg.executor == "falso" and cliente_llm is None:
        raise FalhaExecucao("KORDA_EXECUTOR=falso é só para testes: exige um cliente LLM falso")
    validar_plano(plano)
    if "construction" in plano:
        raise FalhaExecucao("o plano já tem construção; planeje a partir do plano base")
    validar_contexto(contexto, plano)
    if cliente_llm is None:
        cliente_llm = ClienteChatHttp(cfg.llm_url, cfg.chave_api, cfg.modelo, max_tokens=MAX_TOKENS_PLANEJAMENTO)

    carimbo = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    pasta = Path(raiz).resolve() / "planejamento" / f"{plano['plan_version'][:16]}-{carimbo}"
    pasta.mkdir(parents=True, exist_ok=False)
    synthetic = not cfg.usa_llm
    inicio = time.monotonic()
    doc = gerar_documento_base(cliente_llm, contexto, projetar_plano(plano),
                               precos=(cfg.preco_entrada_usd_mtok, cfg.preco_saida_usd_mtok))
    documento = remover_bloco_decisao(doc.texto)
    aviso = "<!-- SINTÉTICO: gerado por cliente falso de teste, sem LLM. -->\n\n" if synthetic else ""
    (pasta / "documento_base.md").write_text(aviso + documento, encoding="utf-8")
    _gravar(pasta / "resposta.json", {"texto": doc.texto})  # resposta bruta, para auditoria
    _gravar(pasta / "medicao.json", {
        "etapa": "planejamento", "executor": cfg.executor, "modelo": cfg.modelo if cfg.usa_llm else None,
        "synthetic": synthetic, "chamadas": 1, "tokens_entrada": doc.tokens_entrada, "tokens_saida": doc.tokens_saida,
        "custo_usd": doc.custo_usd, "custo_centavos": usd_para_centavos(doc.custo_usd, cfg.taxa_usd_brl),
        "custo_estimado": True, "duracao_s": round(time.monotonic() - inicio, 3),
        "secoes_ausentes": doc.secoes_ausentes, "pronto_para_construir": doc.pronto_para_construir,
        "finish_reason": doc.finish_reason,
    })
    if doc.finish_reason == "length":
        raise FalhaExecucao(f"resposta cortada no limite de {MAX_TOKENS_PLANEJAMENTO} tokens; veja {pasta}")
    if doc.pronto_para_construir is None:
        raise FalhaExecucao(f"a resposta do planejamento não trouxe a decisão (bloco json); veja {pasta}")
    if not doc.pronto_para_construir:
        _gravar(pasta / "perguntas.json", {
            "synthetic": synthetic, "project_id": plano["project_id"], "plan_version": plano["plan_version"],
            "context_id": plano["context_id"], "context_revision": plano["context_revision"],
            "perguntas": doc.perguntas})
        return {"estado": "perguntas", "perguntas": doc.perguntas, "pasta": str(pasta)}
    construido = anexar_construcao(plano, {"document": documento, "model": cfg.modelo if cfg.usa_llm else "falso",
                                           "synthetic": synthetic})
    _gravar(pasta / "plano.json", construido)
    return {"estado": "pronto", "plano": construido, "pasta": str(pasta),
            "secoes_ausentes": doc.secoes_ausentes}
