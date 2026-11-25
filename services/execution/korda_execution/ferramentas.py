"""Ferramentas restritas que o harness (K10) vai expor ao agente executor.

Cada ferramenta devolve um dicionário serializável em JSON (`ok`, mais dados ou `erro`)
e registra um evento. Recusas de política não levantam exceção: viram resposta para o
agente corrigir o pedido.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from . import caminhos
from .eventos import EmissorEventos
from .sandbox import DIR_SAIDA, ErroSandbox, ResultadoComando, Sandbox

BANCO_SAIDA = f"{DIR_SAIDA}/korda.duckdb"
LIMITE_LEITURA = 100_000
TIMEOUT_DBT_S = 300
TIMEOUT_CONSULTA_S = 60


@dataclass
class FerramentasRestritas:
    sandbox: Sandbox
    eventos: EmissorEventos
    step: str = "construcao"
    attempt: int = 1

    def _evento(self, type: str, message: str, **extra) -> None:
        self.eventos.emit_event(self.step, type, message, self.attempt, **extra)

    def _recusa(self, ferramenta: str, motivo: str) -> dict:
        self._evento("tool_refused", f"{ferramenta}: {motivo}", ferramenta=ferramenta)
        return {"ok": False, "erro": motivo}

    def escrever_modelo(self, caminho: str, conteudo: str) -> dict:
        try:
            destino = caminhos.caminho_modelo(caminho)
        except caminhos.CaminhoRecusado as e:
            return self._recusa("escrever_modelo", str(e))
        dados = conteudo.encode("utf-8")
        try:
            self.sandbox.enviar_arquivos({destino: dados})
        except ErroSandbox as e:
            return self._recusa("escrever_modelo", str(e))
        self._evento("file_written", caminho, caminho=caminho, bytes=len(dados))
        return {"ok": True, "caminho": caminho}

    def ler_arquivo(self, caminho: str) -> dict:
        try:
            origem = caminhos.caminho_leitura(caminho)
        except caminhos.CaminhoRecusado as e:
            return self._recusa("ler_arquivo", str(e))
        r = self.sandbox.rodar_comando(["head", "-c", str(LIMITE_LEITURA), "--", origem], timeout_s=15)
        if not r.ok:
            return {"ok": False, "erro": r.stderr.strip() or "leitura falhou"}
        return {"ok": True, "caminho": caminho, "conteudo": r.stdout}

    def rodar_dbt(self, subcomando: str, selecao: str | None = None) -> dict:
        try:
            argv = caminhos.argv_dbt(subcomando, selecao)
        except caminhos.CaminhoRecusado as e:
            return self._recusa("rodar_dbt", str(e))
        r = self.sandbox.rodar_comando(argv, timeout_s=TIMEOUT_DBT_S)
        tipo = "dbt_passed" if r.ok else "dbt_failed"
        self._evento(tipo, " ".join(argv[2:]), codigo=r.codigo, duracao_s=r.duracao_s,
                     estourou_tempo=r.estourou_tempo)
        return _resultado(r)

    def consultar_sql(self, sql: str) -> dict:
        if not sql.strip():
            return self._recusa("consultar_sql", "consulta vazia")
        r = self.sandbox.rodar_comando(
            ["python", "/opt/korda/consulta.py", BANCO_SAIDA],
            timeout_s=TIMEOUT_CONSULTA_S,
            stdin=sql.encode("utf-8"),
        )
        try:
            corpo = json.loads(r.stdout) if r.stdout.strip() else {}
        except json.JSONDecodeError:
            corpo = {}
        if not r.ok or "erro" in corpo:
            erro = corpo.get("erro") or r.stderr.strip() or "consulta falhou"
            self._evento("query_failed", erro)
            return {"ok": False, "erro": erro, "estourou_tempo": r.estourou_tempo}
        self._evento("query_finished", f"{len(corpo.get('linhas', []))} linha(s)")
        return {"ok": True, **corpo}


def _resultado(r: ResultadoComando) -> dict:
    return {
        "ok": r.ok,
        "codigo": r.codigo,
        "estourou_tempo": r.estourou_tempo,
        "duracao_s": r.duracao_s,
        "stdout": r.stdout,
        "stderr": r.stderr,
    }
