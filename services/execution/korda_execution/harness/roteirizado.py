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


class ConstrutorRoteirizado:
    """Plano B da demo: copia o pipeline feito à mão para a sandbox. Sem LLM, custo zero.

    Não demonstra construção por IA; existe para a demo não depender do LLM.
    """

    nome = "roteirizado"

    def __init__(self, ferramentas: FerramentasAgente, modelos: dict[str, str]):
        self.ferramentas = ferramentas
        self.modelos = dict(modelos)

    def construir(self, documento_base: str | None) -> dict:
        for caminho, conteudo in sorted(self.modelos.items()):
            resultado = self.ferramentas.escrever_modelo(caminho, conteudo)
            if not resultado.get("ok"):
                return {"ok": False, "erro": f"{caminho}: {resultado.get('erro', 'escrita recusada')}",
                        "custo_centavos": 0}
        return {"ok": True, "custo_centavos": 0}


class RestauradorRoteirizado:
    """Restaura apenas os modelos autorizados que diferem da referência desta execução."""

    def __init__(self, ferramentas: FerramentasAgente, modelos: dict[str, str]):
        self.ferramentas = ferramentas
        self.modelos = modelos

    def __call__(self, falha: dict, tentativa: int) -> dict:
        alterados = {}
        for nome, correto in self.modelos.items():
            atual = self.ferramentas.ler_arquivo(nome)
            if not atual.get("ok"):
                return {"ok": False, "erro": f"não foi possível ler {nome}", "custo_centavos": 0}
            if atual["conteudo"] != correto:
                alterados[nome] = correto
        if not alterados:
            return {"ok": False, "erro": "os modelos já correspondem à referência", "custo_centavos": 0}
        return ConstrutorRoteirizado(self.ferramentas, alterados).construir(None)
