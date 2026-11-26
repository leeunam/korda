"""Exportação técnica para staging privado da execução; promoção é externa ao pipeline."""

import csv
import json
import os
from pathlib import Path
import tempfile

from ingerir import BANCO

PEDIDO = ("pedido_id", "viagem_id", "tipo_viagem", "elegivel_custo", "custo_frete_rateado", "ctes",
          "data_prevista", "data_realizada", "elegivel_otif", "no_prazo", "completo", "otif",
          "entrega_id", "arquivo_pedido", "linha_pedido", "arquivo_entrega", "linha_entrega",
          "chave_nfe", "qt_itens", "qt_entregue", "peso_decimos_kg")
VIAGEM = ("viagem_id", "veiculo_id", "tipo_viagem", "n_entregas", "n_entregas_elegiveis_custo",
          "carga", "capacidade", "unidade", "ocupacao", "acima_capacidade", "custo_frete_total", "custo_por_entrega",
          "arquivo_viagem", "linha_viagem", "arquivo_veiculo", "linha_veiculo")


def ler_linhagem(conn):
    campos = ("chave_cte", "arquivo", "sha256", "frete_centavos", "parcela_centavos")
    consulta = conn.execute("select pedido_id, chave_cte, arquivo, sha256, valor_centavos, centavos "
                            "from prata_rateios order by pedido_id, chave_cte")
    por_pedido = {}
    while lote := consulta.fetchmany(1000):
        for pedido, chave, arquivo, digest, frete, parcela in lote:
            dados = (chave, arquivo, digest, int(frete), int(parcela))
            por_pedido.setdefault(pedido, []).append(dict(zip(campos, dados, strict=True)))
    return por_pedido


def exportar(conn, destino):
    cols = ("custo_frete_por_entrega", "otif_pct", "ocupacao_pct")
    linhas = conn.execute(f"select {', '.join(cols)} from ouro_kpis").fetchall()
    if len(linhas) != 1:
        raise ValueError("o agregado deve produzir exatamente uma linha")
    with tempfile.TemporaryDirectory(dir=destino.parent) as temp:
        staging = Path(temp) / "resultados"
        staging.mkdir()
        kpis = {chave: float(valor) if valor is not None else None
                for chave, valor in zip(cols, linhas[0], strict=True)}
        (staging / "kpis.json").write_text(json.dumps({"kpis": kpis}, allow_nan=False) + "\n", encoding="utf-8")
        linhagem = ler_linhagem(conn)
        for nome, campos in (("por_pedido", PEDIDO), ("por_viagem", VIAGEM)):
            cursor = conn.execute(f"select {', '.join(campos)} from ouro_{nome} order by {campos[0]}")
            with (staging / f"{nome}.csv").open("w", encoding="utf-8", newline="") as fp:
                writer = csv.writer(fp, lineterminator="\n")
                incluir_xml = nome == "por_pedido"
                writer.writerow((*campos, "linhagem_cte") if incluir_xml else campos)
                while lote := cursor.fetchmany(1000):
                    if incluir_xml:
                        for registro in lote:
                            fontes = json.dumps(linhagem.get(registro[0], []), ensure_ascii=False, separators=(",", ":"))
                            writer.writerow((*registro, fontes))
                    else:
                        writer.writerows(lote)
        os.rename(staging, destino)


if __name__ == "__main__":
    import duckdb

    with duckdb.connect(BANCO, read_only=True) as banco:
        exportar(banco, Path("/work/saida/resultados"))
