"""Ferramentas falsas em memória com o mesmo contrato de FerramentasRestritas (#21).

Recusam escrita fora de editable_models, como a classe real, para que os testes
do harness não dependam da sandbox Docker nem do PR #21.
"""

from __future__ import annotations

from korda_execution import caminhos


class FerramentasFalsas:
    def __init__(self, modelos: dict[str, str], editable_models, resultados_dbt: list[dict] | None = None,
                 plano: dict | None = None):
        self.modelos = dict(modelos)
        self.editable_models = frozenset(editable_models)
        self.resultados_dbt = list(resultados_dbt or [])
        self.plano = plano if plano is not None else {"plan_version": "0" * 64}
        self.chamadas: list[tuple[str, tuple]] = []

    def _registrar(self, nome, *args):
        self.chamadas.append((nome, args))

    def escritas(self) -> list[str]:
        return [args[0] for nome, args in self.chamadas if nome == "escrever_modelo_ok"]

    def ler_plano(self) -> dict:
        self._registrar("ler_plano")
        return {"ok": True, "plano": dict(self.plano)}

    def inspecionar_fonte(self, fonte: str) -> dict:
        self._registrar("inspecionar_fonte", fonte)
        return {"ok": True, "perfil": {"fonte": fonte, "linhas": 4}}

    def ler_arquivo(self, caminho: str) -> dict:
        self._registrar("ler_arquivo", caminho)
        if caminho not in self.modelos:
            return {"ok": False, "erro": "arquivo inexistente"}
        return {"ok": True, "caminho": caminho, "conteudo": self.modelos[caminho]}

    def escrever_modelo(self, caminho: str, conteudo: str) -> dict:
        self._registrar("escrever_modelo", caminho, conteudo)
        try:
            caminhos.caminho_modelo(caminho)
        except caminhos.CaminhoRecusado as e:
            return {"ok": False, "erro": str(e)}
        if caminho not in self.editable_models:
            return {"ok": False, "erro": "modelo fora do escopo aprovado"}
        self.modelos[caminho] = conteudo
        self._registrar("escrever_modelo_ok", caminho)
        return {"ok": True, "caminho": caminho}

    def rodar_dbt(self, subcomando: str, selecao: str | None = None) -> dict:
        self._registrar("rodar_dbt", subcomando, selecao)
        if self.resultados_dbt:
            return self.resultados_dbt.pop(0)
        return {"ok": True, "codigo": 0, "estourou_tempo": False, "duracao_s": 0.1, "stdout": "PASS", "stderr": ""}

    def consultar_sql(self, sql: str) -> dict:
        self._registrar("consultar_sql", sql)
        return {"ok": True, "colunas": ["n"], "linhas": [[1]]}
