"""Consulta SQL somente leitura dentro da sandbox.

Lê o SQL do stdin e imprime o resultado como JSON. A conexão é read_only e o acesso
externo (arquivos, rede, extensões) é desligado antes da consulta, então `COPY ... TO`,
`read_csv` e `ATTACH` falham. Uso: python /opt/korda/consulta.py <banco.duckdb> < consulta.sql
"""

import json
import sys

import duckdb

LIMITE_LINHAS = 200


def main():
    if len(sys.argv) != 2:
        print("uso: consulta.py <banco.duckdb>", file=sys.stderr)
        return 2
    sql = sys.stdin.read()
    con = duckdb.connect(sys.argv[1], read_only=True)
    try:
        con.execute("SET enable_external_access = false")
        con.execute("SET lock_configuration = true")
        cursor = con.execute(sql)
        colunas = [d[0] for d in cursor.description] if cursor.description else []
        linhas = cursor.fetchmany(LIMITE_LINHAS + 1)
    except duckdb.Error as erro:
        print(json.dumps({"erro": str(erro)}, ensure_ascii=False))
        return 1
    finally:
        con.close()
    print(json.dumps(
        {
            "colunas": colunas,
            "linhas": [list(l) for l in linhas[:LIMITE_LINHAS]],
            "truncado": len(linhas) > LIMITE_LINHAS,
        },
        ensure_ascii=False,
        default=str,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
