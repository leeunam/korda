"""Exporta as tabelas prata (`prata_*`) para Parquet, para a entrega mostrar onde está o dado limpo.

Roda na sandbox depois de `exportar.py`, com o banco aberto só para leitura. Escreve
`/work/saida/prata/<tabela>.parquet` e `linhas.json` ({tabela: número de linhas}). Tabelas cujo
nome foge do padrão `prata_[a-z0-9_]` não são exportadas (o nome vira nome de arquivo).
"""

import json
import re
import shutil
from pathlib import Path

from ingerir import BANCO

DESTINO = Path("/work/saida/prata")
NOME = re.compile(r"prata_[a-z0-9_]{1,58}")
MAX_TABELAS = 50


def exportar_prata(conn, destino):
    nomes = [linha[0] for linha in conn.execute(
        "select table_name from information_schema.tables "
        "where table_schema = 'main' and starts_with(table_name, 'prata_') order by table_name").fetchall()]
    tabelas = [n for n in nomes if NOME.fullmatch(n)]
    if len(tabelas) > MAX_TABELAS:
        raise ValueError(f"mais de {MAX_TABELAS} tabelas prata")
    if destino.exists():  # nova tentativa de build: a exportação anterior é descartada
        shutil.rmtree(destino)
    destino.mkdir(parents=True)
    linhas = {}
    for tabela in tabelas:
        # O nome já casou com NOME: só letras minúsculas, dígitos e _. A ordem fixa torna o Parquet
        # reproduzível (mesmos dados, mesmos bytes), o que permite conferir uma reexecução pelo hash.
        conn.execute(f"copy (select * from \"{tabela}\" order by all) to '{destino / tabela}.parquet' "
                     "(format parquet)")
        linhas[tabela] = conn.execute(f"select count(*) from \"{tabela}\"").fetchone()[0]
    (destino / "linhas.json").write_text(json.dumps(linhas, sort_keys=True) + "\n", encoding="utf-8")
    return linhas


if __name__ == "__main__":
    import duckdb

    with duckdb.connect(BANCO, read_only=True) as banco:
        exportar_prata(banco, DESTINO)
