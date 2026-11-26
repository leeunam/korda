"""Configuração do harness lida do ambiente, com o portão da chave do LLM.

O LLM real só roda com três sinais juntos: KORDA_CORRETOR=agente,
KORDA_PERMITIR_LLM_REAL=1 e ANTHROPIC_API_KEY preenchida. Qualquer outra
combinação usa um corretor sem LLM ou falha com uma mensagem clara.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

CORRETORES = ("roteirizado", "agente", "falso")
Corretor = Literal["roteirizado", "agente", "falso"]


class ErroConfiguracao(ValueError):
    """Ambiente incompatível com o corretor pedido."""


def _positivo(env: Mapping[str, str], nome: str, padrao: str) -> float:
    bruto = env.get(nome, "").strip() or padrao
    try:
        valor = float(bruto)
    except ValueError:
        raise ErroConfiguracao(f"{nome} deve ser um número positivo, recebido {bruto!r}") from None
    if not math.isfinite(valor) or valor <= 0:
        raise ErroConfiguracao(f"{nome} deve ser um número positivo, recebido {bruto!r}")
    return valor


@dataclass(frozen=True)
class ConfigHarness:
    corretor: Corretor
    modelo: str
    orcamento_execucao_usd: float
    max_turnos_tentativa: int
    taxa_usd_brl: float
    permitir_llm_real: bool
    chave_api: str | None = field(default=None, repr=False)

    @classmethod
    def de_ambiente(cls, env: Mapping[str, str] | None = None) -> "ConfigHarness":
        env = os.environ if env is None else env
        corretor = env.get("KORDA_CORRETOR", "").strip() or "roteirizado"
        if corretor not in CORRETORES:
            raise ErroConfiguracao(f"KORDA_CORRETOR deve ser um de {', '.join(CORRETORES)}; recebido {corretor!r}")
        modelo = env.get("KORDA_MODELO", "claude-opus-5-5").strip()
        if not modelo:
            raise ErroConfiguracao("KORDA_MODELO não pode ser vazio")
        turnos_bruto = env.get("KORDA_MAX_TURNOS_TENTATIVA", "").strip() or "12"
        if not turnos_bruto.isdigit() or int(turnos_bruto) < 1:
            raise ErroConfiguracao(f"KORDA_MAX_TURNOS_TENTATIVA deve ser um inteiro ≥ 1, recebido {turnos_bruto!r}")
        permitir = env.get("KORDA_PERMITIR_LLM_REAL", "").strip() == "1"
        chave = env.get("ANTHROPIC_API_KEY", "").strip() or None
        if corretor == "agente":
            if not permitir:
                raise ErroConfiguracao(
                    "KORDA_CORRETOR=agente chama o LLM e gasta créditos; defina KORDA_PERMITIR_LLM_REAL=1 "
                    "somente com autorização do responsável pela chave"
                )
            if chave is None:
                raise ErroConfiguracao(
                    "ANTHROPIC_API_KEY ausente ou vazia: exporte a chave fornecida pelo responsável "
                    "(ver .env.example) ou use KORDA_CORRETOR=roteirizado"
                )
        return cls(
            corretor=corretor,
            modelo=modelo,
            orcamento_execucao_usd=_positivo(env, "KORDA_ORCAMENTO_EXECUCAO_USD", "3.00"),
            max_turnos_tentativa=int(turnos_bruto),
            taxa_usd_brl=_positivo(env, "KORDA_TAXA_USD_BRL", "6.00"),
            permitir_llm_real=permitir,
            chave_api=chave,
        )
