"""Ferramentas restritas que o harness (K10) expõe ao agente executor.

Cada ferramenta devolve um dicionário serializável em JSON (`ok`, mais dados ou `erro`)
e registra um evento. Recusas de política não levantam exceção: viram resposta para o
agente corrigir o pedido.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass

from . import caminhos
from .eventos import EmissorEventos
from .sandbox import DIR_SAIDA, ErroSandbox, ResultadoComando, Sandbox

BANCO_SAIDA = f"{DIR_SAIDA}/korda.duckdb"
LIMITE_LEITURA = 16_000
TIMEOUT_DBT_S = 300
TIMEOUT_CONSULTA_S = 60
FONTES = frozenset({"erp_clientes", "erp_pedidos", "tms_veiculos", "tms_viagens", "tms_entregas", "cte"})


@dataclass
class FerramentasRestritas:
    sandbox: Sandbox
    eventos: EmissorEventos
    step: str = "construcao"
    attempt: int = 1
    plano_aprovado: dict | None = None
    modelos_permitidos: frozenset[str] | None = None

    def __post_init__(self) -> None:
        # O coordenador valida a aprovação e projeta o plano antes de oferecê-lo às ferramentas.
        self.plano_aprovado = deepcopy(self.plano_aprovado)
        if self.modelos_permitidos is not None:
            self.modelos_permitidos = frozenset(self.modelos_permitidos)
            for padrao in self.modelos_permitidos:
                caminhos.padrao_modelo(padrao)

    def _evento(self, type: str, message: str, **extra) -> None:
        self.eventos.emit_event(self.step, type, message, self.attempt, **extra)

    def _recusa(self, ferramenta: str, motivo: str) -> dict:
        self._evento("tool_refused", f"{ferramenta}: {motivo}", ferramenta=ferramenta)
        return {"ok": False, "erro": motivo}

    def ler_plano(self) -> dict:
        if self.plano_aprovado is None:
            return self._recusa("ler_plano", "nenhum plano aprovado foi associado à execução")
        self._evento("plan_read", "Plano aprovado consultado", plan_version=self.plano_aprovado.get("plan_version"))
        return {"ok": True, "plano": deepcopy(self.plano_aprovado)}

    def inspecionar_fonte(self, fonte: str) -> dict:
        if not isinstance(fonte, str) or fonte not in FONTES:
            return self._recusa("inspecionar_fonte", "fonte fora do catálogo autorizado")
        r = self.sandbox.rodar_comando(["python", "/opt/korda/perfil.py", fonte], timeout_s=30)
        corpo = _objeto_json(r.stdout)
        if not r.ok or corpo.get("fonte") != fonte:
            return self._recusa("inspecionar_fonte", corpo.get("erro") or "não foi possível obter o perfil")
        self._evento("source_profiled", fonte, fonte=fonte, perfil=corpo)
        return {"ok": True, "perfil": corpo}

    def escrever_modelo(self, caminho: str, conteudo: str) -> dict:
        try:
            destino = caminhos.caminho_modelo(caminho)
        except caminhos.CaminhoRecusado as e:
            return self._recusa("escrever_modelo", str(e))
        if self.plano_aprovado is not None or self.modelos_permitidos is not None:
            if not caminhos.modelo_autorizado(caminho, self.modelos_permitidos or ()):
                return self._recusa("escrever_modelo", "modelo fora do escopo aprovado")
        if not isinstance(conteudo, str):
            return self._recusa("escrever_modelo", "conteúdo SQL deve ser texto")
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
        r = self.sandbox.rodar_comando(["head", "-c", str(LIMITE_LEITURA + 1), "--", origem], timeout_s=15)
        if not r.ok:
            return {"ok": False, "erro": r.stderr.strip() or "leitura falhou"}
        if len(r.stdout.encode("utf-8")) > LIMITE_LEITURA:
            return self._recusa("ler_arquivo", f"arquivo excede {LIMITE_LEITURA} bytes")
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
        if not isinstance(sql, str) or not sql.strip():
            return self._recusa("consultar_sql", "consulta vazia")
        r = self.sandbox.rodar_comando(
            ["python", "/opt/korda/consulta.py", BANCO_SAIDA],
            timeout_s=TIMEOUT_CONSULTA_S,
            stdin=sql.encode("utf-8"),
        )
        corpo = _objeto_json(r.stdout)
        if not r.ok or "erro" in corpo or not isinstance(corpo.get("linhas"), list):
            erro = corpo.get("erro") or r.stderr.strip() or "resultado da consulta inválido ou grande demais"
            self._evento("query_failed", erro)
            return {"ok": False, "erro": erro, "estourou_tempo": r.estourou_tempo}
        self._evento("query_finished", f"{len(corpo.get('linhas', []))} linha(s)")
        return {"ok": True, **corpo}


def _objeto_json(texto: str) -> dict:
    try:
        objeto = json.loads(texto)
    except ValueError:
        return {}
    return objeto if isinstance(objeto, dict) else {}


def _resultado(r: ResultadoComando) -> dict:
    return {
        "ok": r.ok,
        "codigo": r.codigo,
        "estourou_tempo": r.estourou_tempo,
        "duracao_s": r.duracao_s,
        "stdout": r.stdout,
        "stderr": r.stderr,
    }
