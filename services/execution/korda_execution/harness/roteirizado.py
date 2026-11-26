"""Corretor roteirizado: plano B da demo, sem LLM.

Reproduz o `corrigir` atual do worker (#21): restaura a versão revisada do
modelo autorizado. Não descobre nada; só prova o ciclo. Custo zero.
"""

from __future__ import annotations

from collections.abc import Callable

from .tipos import FerramentasAgente


class CorretorRoteirizado:
    nome = "roteirizado"

    def __init__(self, ferramentas: FerramentasAgente, modelo: str, conteudo_correto: Callable[[], str]):
        self.ferramentas = ferramentas
        self.modelo = modelo
        self.conteudo_correto = conteudo_correto

    def __call__(self, falha: dict, tentativa: int) -> dict:
        correto = self.conteudo_correto()
        atual = self.ferramentas.ler_arquivo(self.modelo)
        if not atual.get("ok") or atual.get("conteudo") == correto:
            return {"ok": False, "erro": "modelo indisponível ou já corresponde à versão revisada", "custo_centavos": 0}
        alteracao = self.ferramentas.escrever_modelo(self.modelo, correto)
        return {**alteracao, "custo_centavos": 0}
