"""Contratos estreitos de que o harness depende.

`Corretor` tem a assinatura do `corrigir` do worker (#21). `FerramentasAgente`
espelha os seis métodos de `FerramentasRestritas` (#21) sem importar a classe,
para o harness não depender do merge. Se o #21 mudar essas assinaturas, o
ajuste fica aqui e em `ferramentas_agente.py`.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Protocol, runtime_checkable


@runtime_checkable
class Corretor(Protocol):
    def __call__(self, falha: dict, tentativa: int) -> dict:
        """Devolve {"ok": bool, "erro"?: str, "custo_centavos": int | None}.

        `ok: True` significa que alguma alteração foi aplicada; quem decide se
        ela resolveu é o rebuild. `custo_centavos` None indica custo desconhecido
        (o ciclo de correção escala em vez de assumir zero).
        """


@runtime_checkable
class FerramentasAgente(Protocol):
    def ler_plano(self) -> dict: ...
    def inspecionar_fonte(self, fonte: str) -> dict: ...
    def ler_arquivo(self, caminho: str) -> dict: ...
    def escrever_modelo(self, caminho: str, conteudo: str) -> dict: ...
    def rodar_dbt(self, subcomando: str, selecao: str | None = None) -> dict: ...
    def consultar_sql(self, sql: str) -> dict: ...


@dataclass
class ResultadoTentativa:
    tentativa: int
    corretor: str
    ok: bool
    motivo_parada: str
    turnos: int
    tokens_entrada: int
    tokens_saida: int
    tokens_cache_leitura: int
    custo_usd: float | None
    custo_centavos: int | None
    duracao_s: float
    arquivos_escritos: list[str] = field(default_factory=list)

    def como_dict(self) -> dict:
        return asdict(self)


@dataclass
class SaidaSessao:
    """Resultado de uma sessão de agente (chat ou SDK)."""
    subtype: str
    num_turns: int
    total_cost_usd: float | None
    usage: dict
    ferramentas_sessao: list[str] = field(default_factory=list)
    erro: str | None = None  # mensagem de ErroLLM (sem segredo), quando a API falhou
    tokens_por_turno: list[list[int]] = field(default_factory=list)  # [entrada, saída] de cada chamada


def usd_para_centavos(usd: float | None, taxa: float) -> int | None:
    """Converte dólares em centavos de real, arredondando para cima."""
    if usd is None:
        return None
    if usd < 0:
        raise ValueError("custo negativo")
    return math.ceil(round(usd * taxa * 100, 6))
