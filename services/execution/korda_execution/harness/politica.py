"""Política das ferramentas do agente e hook PreToolUse do Claude Agent SDK.

É a terceira camada de proteção. A primeira é o kernel: a sandbox monta o
projeto em modo somente leitura e só os arquivos de editable_models graváveis.
A segunda é `caminhos.py` + `FerramentasRestritas`. Esta camada recusa cedo,
com uma mensagem para o agente, e registra a recusa como evento.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .. import caminhos

PREFIXO = "mcp__korda__"
FERRAMENTAS = ("ler_plano", "inspecionar_fonte", "ler_arquivo", "escrever_modelo", "rodar_dbt", "consultar_sql")
STEP = "construcao"


@dataclass(frozen=True)
class Decisao:
    permitir: bool
    motivo: str


def nome_curto(nome: str) -> str | None:
    """Nome da ferramenta korda sem o prefixo MCP, ou None se não for uma delas."""
    if isinstance(nome, str) and nome.startswith(PREFIXO) and nome[len(PREFIXO):] in FERRAMENTAS:
        return nome[len(PREFIXO):]
    return None


def modelo_autorizado(caminho: str, editable_models) -> bool:
    """Caminho exato ou padrão glob (ex.: `models/*`) de editable_models. Ver `caminhos.modelo_autorizado`."""
    return caminhos.modelo_autorizado(caminho, editable_models)


def avaliar_chamada(nome: str, entrada: dict, editable_models: frozenset[str]) -> Decisao:
    curto = nome_curto(nome)
    if curto is None:
        return Decisao(False, "ferramenta fora do catálogo do executor; use somente as ferramentas mcp__korda__*")
    if curto == "escrever_modelo":
        caminho = entrada.get("caminho") if isinstance(entrada, dict) else None
        if not isinstance(caminho, str):
            return Decisao(False, "escrever_modelo exige o caminho do modelo")
        try:
            caminhos.caminho_modelo(caminho)
        except caminhos.CaminhoRecusado as e:
            return Decisao(False, str(e))
        if not modelo_autorizado(caminho, editable_models):
            return Decisao(False, "modelo fora do escopo aprovado; permitidos: " + ", ".join(sorted(editable_models)))
    return Decisao(True, "permitido")


HookPreToolUse = Callable[[dict, str | None, Any], Awaitable[dict]]


def hook_pre_tool_use(editable_models, emissor=None, *, obter_tentativa: Callable[[], int] = lambda: 1) -> HookPreToolUse:
    """Hook PreToolUse: `{}` permite; a recusa devolve permissionDecision=deny."""
    editaveis = frozenset(editable_models)

    async def hook(input_data: dict, tool_use_id: str | None, context: Any) -> dict:
        nome = input_data.get("tool_name", "")
        decisao = avaliar_chamada(nome, input_data.get("tool_input") or {}, editaveis)
        if decisao.permitir:
            return {}
        ferramenta = nome_curto(nome) or str(nome)[:80]
        if emissor is not None:
            emissor.emit_event(STEP, "tool_refused", f"{ferramenta}: {decisao.motivo}", obter_tentativa(),
                               ferramenta=ferramenta, origem="hook")
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": decisao.motivo}}

    return hook
