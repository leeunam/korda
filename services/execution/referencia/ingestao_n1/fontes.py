"""Leitura das três fontes conforme o plano: ERP (Postgres), TMS (API HTTP) e CT-e (pasta)."""

from __future__ import annotations

import datetime as dt
import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path


class Escalar(Exception):
    """Mudança de esquema (ou outra situação que exige decisão humana): nada é gravado."""

    def __init__(self, motivo: str, detalhes: dict):
        super().__init__(motivo)
        self.motivo = motivo
        self.detalhes = detalhes


class FalhaFonte(Exception):
    """A fonte não respondeu dentro do limite de tentativas do plano."""


@dataclass
class Tentativas:
    total: int = 0
    por_motivo: dict = field(default_factory=dict)

    def registrar(self, motivo: str) -> None:
        self.total += 1
        self.por_motivo[motivo] = self.por_motivo.get(motivo, 0) + 1


def _env(nome: str, permitidos: list[str]) -> str:
    if nome not in permitidos:
        raise FalhaFonte(f"variável {nome} não está em credentials_env do plano")
    valor = os.environ.get(nome)
    if not valor:
        raise FalhaFonte(f"variável de ambiente {nome} ausente")
    return valor


def _esperar(res: dict, i: int, retry_after: str | None = None) -> None:
    if retry_after and retry_after.isdigit():
        time.sleep(int(retry_after))
        return
    esperas = res["backoff_seconds"] or [1]
    time.sleep(esperas[min(i, len(esperas) - 1)])


# ERP ---------------------------------------------------------------------------------------

def ler_erp(fonte: dict, tentativas: Tentativas) -> dict[str, tuple[list[str], list[list]]]:
    """Snapshot completo de cada tabela: (colunas, linhas como texto do Postgres)."""
    import psycopg
    from psycopg import sql

    env = fonte["credentials_env"]
    res = fonte["resilience"]
    params = dict(host=_env("KORDA_ERP_HOST", env), port=_env("KORDA_ERP_PORTA", env),
                  dbname=_env("KORDA_ERP_BANCO", env), user=_env("KORDA_ERP_USUARIO", env),
                  password=_env("KORDA_ERP_SENHA", env), connect_timeout=int(res["timeout_seconds"]))
    for i in range(res["max_retries"] + 1):
        try:
            with psycopg.connect(**params, options="-c default_transaction_read_only=on") as con:
                saida = {}
                for obj in fonte["objects"]:
                    tabela = obj["locator"]
                    cols = [r[0] for r in con.execute(
                        "select column_name from information_schema.columns "
                        "where table_schema = 'public' and table_name = %s order by ordinal_position",
                        [tabela]).fetchall()]
                    if not cols:
                        raise Escalar("tabela_ausente", {"fonte": fonte["id"], "objeto": obj["name"], "tabela": tabela})
                    selecao = sql.SQL(", ").join(sql.SQL("{}::text").format(sql.Identifier(c)) for c in cols)
                    ordem = sql.SQL(", ").join(sql.Identifier(c) for c in (obj["key"] or cols[:1]))
                    linhas = con.execute(sql.SQL("select {} from {} order by {}").format(
                        selecao, sql.Identifier(tabela), ordem)).fetchall()
                    saida[obj["name"]] = (cols, [list(l) for l in linhas])
                return saida
        except psycopg.OperationalError as e:
            if "conexao" not in res["retry_on"] or i == res["max_retries"]:
                raise FalhaFonte(f"ERP indisponível: {e}") from e
            tentativas.registrar("conexao")
            _esperar(res, i)
    raise FalhaFonte("ERP indisponível")


# TMS ---------------------------------------------------------------------------------------

def _get(url: str, token: str, res: dict, tentativas: Tentativas) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    for i in range(res["max_retries"] + 1):
        motivo, retry_after = None, None
        try:
            with urllib.request.urlopen(req, timeout=res["timeout_seconds"]) as r:
                # Números chegam como o texto do JSON: nada é reformatado.
                return json.loads(r.read().decode("utf-8"), parse_int=str, parse_float=str)
        except urllib.error.HTTPError as e:
            motivo, retry_after = str(e.code), e.headers.get("Retry-After")
            if motivo not in res["retry_on"]:
                raise FalhaFonte(f"TMS respondeu {e.code} em {url}") from e
        except (TimeoutError, socket.timeout):
            motivo = "timeout"
        except urllib.error.URLError as e:
            motivo = "timeout" if isinstance(e.reason, (TimeoutError, socket.timeout)) else "conexao"
        if motivo not in res["retry_on"] or i == res["max_retries"]:
            raise FalhaFonte(f"TMS sem resposta válida após {i + 1} tentativa(s) ({motivo}) em {url}")
        tentativas.registrar(motivo)
        _esperar(res, i, retry_after)
    raise FalhaFonte(f"TMS indisponível em {url}")


def ler_tms(fonte: dict, marcas: dict, tentativas: Tentativas) -> dict[str, tuple[list[dict], str | None]]:
    """Registros novos de cada recurso desde a marca anterior: (registros, nova marca)."""
    env = fonte["credentials_env"]
    base = _env("KORDA_TMS_URL", env).rstrip("/")
    token = _env("KORDA_TMS_TOKEN", env)
    campo = fonte["incremental_key"]["field"]
    saida = {}
    for obj in fonte["objects"]:
        marca = marcas.get(obj["name"])
        registros, pagina = [], 1
        while pagina:
            q = {"pagina": pagina, "tamanho": 500}
            if marca:
                q["atualizado_desde"] = marca
            corpo = _get(f"{base}{obj['locator']}?{urllib.parse.urlencode(q)}", token, fonte["resilience"], tentativas)
            registros += corpo["dados"]
            pagina = corpo.get("proxima_pagina")
            pagina = int(pagina) if pagina else None
        nova = marca
        for r in registros:
            valor = r.get(campo)
            if valor and (nova is None or dt.datetime.fromisoformat(valor) > dt.datetime.fromisoformat(nova)):
                nova = valor
        saida[obj["name"]] = (registros, nova)
    return saida


# CT-e --------------------------------------------------------------------------------------

def novos_arquivos(pasta: Path, padrao: str, processados: set[str]) -> list[Path]:
    return sorted(p for p in pasta.glob(padrao) if p.is_file() and p.relative_to(pasta).as_posix() not in processados)
