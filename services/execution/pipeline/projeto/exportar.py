"""Exportação técnica para staging privado da execução; promoção é externa ao pipeline."""

import csv
import json
import os
from pathlib import Path
import tempfile

import yaml

from ingerir import BANCO

def contrato_exportacao():
    projeto = Path(__file__).with_name("dbt_project.yml")
    return yaml.safe_load(projeto.read_text(encoding="utf-8"))["vars"]["contrato_exportacao"]


def ler_linhagem(conn, colunas):
    campos = tuple(colunas)
    consulta = conn.execute(f"select {', '.join(campos)} from prata_rateios order by pedido_id, chave_cte")
    por_pedido = {}
    while lote := consulta.fetchmany(1000):
        for linha in lote:
            rateio = dict(zip(campos, linha, strict=True))
            pedido = rateio.pop("pedido_id")
            rateio["frete_centavos"] = int(rateio.pop("valor_centavos"))
            rateio["parcela_centavos"] = int(rateio.pop("centavos"))
            por_pedido.setdefault(pedido, []).append(rateio)
    return por_pedido


def exportar(conn, destino):
    contrato = contrato_exportacao()
    cols = tuple(contrato["ouro_kpis"])
    linhas = conn.execute(f"select {', '.join(cols)} from ouro_kpis").fetchall()
    if len(linhas) != 1:
        raise ValueError("o agregado deve produzir exatamente uma linha")
    with tempfile.TemporaryDirectory(dir=destino.parent) as temp:
        staging = Path(temp) / "resultados"
        staging.mkdir()
        kpis = {chave: float(valor) if valor is not None else None
                for chave, valor in zip(cols, linhas[0], strict=True)}
        (staging / "kpis.json").write_text(json.dumps({"kpis": kpis}, allow_nan=False) + "\n", encoding="utf-8")
        linhagem = ler_linhagem(conn, contrato["prata_rateios"])
        for nome in ("por_pedido", "por_viagem"):
            campos = tuple(contrato["ouro_" + nome])
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
