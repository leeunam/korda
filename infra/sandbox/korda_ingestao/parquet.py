"""Gravação de tabelas em Parquet pelo DuckDB, com esquema explícito.

As linhas passam por um NDJSON temporário (chaves posicionais c0..cN) lido com
`read_json(columns=...)`. Isso preserva a diferença entre NULL e '' e é ordens de grandeza
mais rápido que `executemany` no duckdb 1.5 (medido: ~200 mil linhas/s contra ~2 mil).
Uma thread, para a saída não depender de agendamento.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb


def ident(nome: str) -> str:
    return '"' + nome.replace('"', '""') + '"'


def literal(texto: str) -> str:
    return "'" + texto.replace("'", "''") + "'"


def conectar() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET threads = 1")
    con.execute("SET preserve_insertion_order = true")
    return con


def gravar(
    con: duckdb.DuckDBPyConnection,
    destino: Path,
    esquema: list[tuple[str, str]],
    linhas: list[list],
    staging: Path,
) -> None:
    """Grava `linhas` (listas na ordem de `esquema`) em `destino`, na ordem recebida."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    staging.mkdir(parents=True, exist_ok=True)
    tmp = staging / (destino.name + ".ndjson")
    chaves = [f"c{i}" for i in range(len(esquema))]
    with tmp.open("w", encoding="utf-8") as f:
        for valores in linhas:
            f.write(json.dumps(dict(zip(chaves, valores)), ensure_ascii=False))
            f.write("\n")
    tipos = ", ".join(f"{literal(k)}: {literal(t)}" for k, (_, t) in zip(chaves, esquema))
    selecao = ", ".join(f"{k} AS {ident(nome)}" for k, (nome, _) in zip(chaves, esquema))
    con.execute(
        f"COPY (SELECT {selecao} FROM read_json({literal(str(tmp))}, format = 'newline_delimited', "
        f"columns = {{{tipos}}})) TO {literal(str(destino))} (FORMAT parquet)"
    )
    tmp.unlink()
