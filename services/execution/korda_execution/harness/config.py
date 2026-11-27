"""Configuração do harness lida do ambiente, com o portão da chave do LLM.

Executores: `roteirizado` (plano B: copia o pipeline feito à mão, sem LLM),
`falso` (testes, sem LLM), `chat` (agente com loop próprio sobre uma API
chat/completions, como o gateway da Feita) e `agente_sdk` (Claude Agent SDK,
exige chave da Anthropic). Os dois últimos gastam créditos e só rodam com
três sinais juntos: o executor, KORDA_PERMITIR_LLM_REAL=1 e a chave.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

EXECUTORES = ("roteirizado", "falso", "chat", "agente_sdk")
Executor = Literal["roteirizado", "falso", "chat", "agente_sdk"]
CHAVE_POR_EXECUTOR = {"chat": "KORDA_LLM_CHAVE", "agente_sdk": "ANTHROPIC_API_KEY"}
MODELO_PADRAO = {"agente_sdk": "claude-opus-5-5"}
MODELO_PADRAO_CHAT = "anthropic/claude-opus-5.5"
URL_PADRAO = "https://api.feita.ai/gateway/v1"


class ErroConfiguracao(ValueError):
    """Ambiente incompatível com o executor pedido."""


def _positivo(env: Mapping[str, str], nome: str, padrao: str) -> float:
    bruto = env.get(nome, "").strip() or padrao
    try:
        valor = float(bruto)
    except ValueError:
        raise ErroConfiguracao(f"{nome} deve ser um número positivo, recebido {bruto!r}") from None
    if not math.isfinite(valor) or valor <= 0:
        raise ErroConfiguracao(f"{nome} deve ser um número positivo, recebido {bruto!r}")
    return valor


def _inteiro(env: Mapping[str, str], nome: str, padrao: str) -> int:
    bruto = env.get(nome, "").strip() or padrao
    if not (bruto.isascii() and bruto.isdigit()) or int(bruto) < 1:
        raise ErroConfiguracao(f"{nome} deve ser um inteiro ≥ 1, recebido {bruto!r}")
    return int(bruto)


@dataclass(frozen=True)
class ConfigHarness:
    executor: Executor
    modelo: str
    llm_url: str
    orcamento_execucao_usd: float
    max_turnos_construcao: int
    max_turnos_tentativa: int
    taxa_usd_brl: float
    preco_entrada_usd_mtok: float
    preco_saida_usd_mtok: float
    permitir_llm_real: bool
    chave_api: str | None = field(default=None, repr=False)

    @property
    def usa_llm(self) -> bool:
        return self.executor in CHAVE_POR_EXECUTOR

    def precos_medicao(self) -> dict:
        return {"entrada_usd_mtok": self.preco_entrada_usd_mtok, "saida_usd_mtok": self.preco_saida_usd_mtok,
                "taxa_usd_brl": self.taxa_usd_brl}

    @classmethod
    def de_ambiente(cls, env: Mapping[str, str] | None = None) -> "ConfigHarness":
        env = os.environ if env is None else env
        if env.get("KORDA_CORRETOR", "").strip():
            raise ErroConfiguracao("KORDA_CORRETOR foi substituída por KORDA_EXECUTOR (ver .env.example)")
        executor = env.get("KORDA_EXECUTOR", "").strip() or "roteirizado"
        if executor not in EXECUTORES:
            raise ErroConfiguracao(f"KORDA_EXECUTOR deve ser um de {', '.join(EXECUTORES)}; recebido {executor!r}")
        modelo = env.get("KORDA_MODELO", "").strip() or MODELO_PADRAO.get(executor, MODELO_PADRAO_CHAT)
        url = (env.get("KORDA_LLM_URL", "").strip() or URL_PADRAO).rstrip("/")
        if not url.startswith("https://"):
            raise ErroConfiguracao(f"KORDA_LLM_URL deve usar https, recebido {url!r}")
        permitir = env.get("KORDA_PERMITIR_LLM_REAL", "").strip() == "1"
        chave = None
        if executor in CHAVE_POR_EXECUTOR:
            nome_chave = CHAVE_POR_EXECUTOR[executor]
            chave = env.get(nome_chave, "").strip() or None
            if not permitir:
                raise ErroConfiguracao(
                    f"KORDA_EXECUTOR={executor} chama o LLM e gasta créditos; defina KORDA_PERMITIR_LLM_REAL=1 "
                    "somente com autorização do responsável pela chave"
                )
            if chave is None:
                raise ErroConfiguracao(
                    f"{nome_chave} ausente ou vazia: exporte a chave fornecida pelo responsável "
                    "(ver .env.example) ou use KORDA_EXECUTOR=roteirizado"
                )
        return cls(
            executor=executor,
            modelo=modelo,
            llm_url=url,
            orcamento_execucao_usd=_positivo(env, "KORDA_ORCAMENTO_EXECUCAO_USD", "8.00"),
            max_turnos_construcao=_inteiro(env, "KORDA_MAX_TURNOS_CONSTRUCAO", "40"),
            max_turnos_tentativa=_inteiro(env, "KORDA_MAX_TURNOS_TENTATIVA", "12"),
            taxa_usd_brl=_positivo(env, "KORDA_TAXA_USD_BRL", "6.00"),
            preco_entrada_usd_mtok=_positivo(env, "KORDA_PRECO_ENTRADA_USD_MTOK", "4.00"),
            preco_saida_usd_mtok=_positivo(env, "KORDA_PRECO_SAIDA_USD_MTOK", "20.00"),
            permitir_llm_real=permitir,
            chave_api=chave,
        )
