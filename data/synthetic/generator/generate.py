"""Gerador de fontes sintéticas (ERP, TMS, CT-e) a partir de empresas/<id>/empresa.yaml.

Uso:
    .venv/bin/python data/synthetic/generator/generate.py --all
    .venv/bin/python data/synthetic/generator/generate.py --empresa 01_demo

Saída em data/synthetic/output/<empresa>/ (ignorada pelo Git; reproduzível pela semente):
    erp/erp_clientes.csv, erp/erp_pedidos.csv
    tms/tms_veiculos.csv, tms/tms_viagens.csv, tms/tms_entregas.csv
    cte/*.xml                          (cteProc e procEventoCTe 4.00, homologação, fictícios)
    _gerador/anomalias_plantadas.csv   (onde cada anomalia foi plantada; o gabarito NÃO lê)
    _gerador/contagens.json            (taxas efetivas e contagens)
A pasta da empresa é recriada a cada execução.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
from anomalies import build_ctes, plant_delivery_anomalies  # noqa: E402
from model import simulate  # noqa: E402
from writers import write_csvs, write_ctes  # noqa: E402


def generate(empresa_id: str, output_root: Path = config.OUTPUT) -> dict:
    ctx = config.load(empresa_id)
    out = (output_root / empresa_id).resolve()
    if output_root.resolve() not in out.parents:
        raise ValueError(f"saída fora de {output_root}: {out}")
    if out.exists():
        shutil.rmtree(out)

    mundo = simulate(ctx)
    registro: list[dict] = []
    plant_delivery_anomalies(mundo, registro)
    ctes = build_ctes(mundo, registro)

    tabelas = write_csvs(mundo, out)
    xmls = write_ctes(mundo, ctes, out)

    meta = out / "_gerador"
    meta.mkdir(parents=True, exist_ok=True)
    with (meta / "anomalias_plantadas.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["tipo", "entidade", "id", "detalhe"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(registro)

    por_tipo = Counter(r["tipo"] for r in registro)
    n_ctes_emitidos = len(ctes)
    entregas_normais = sum(1 for v in mundo.viagens if v.tipo == "DIST" for _ in v.entregas)
    contagens = {
        "empresa_id": empresa_id,
        "uso": ctx.cfg["uso"],
        "semente": ctx.cfg["semente"],
        "taxas_efetivas_sorteadas": {k: round(v, 4) for k, v in mundo.taxas.items()},
        "tabelas": tabelas,
        "viagens": {"total": len(mundo.viagens), "DIST": sum(v.tipo == "DIST" for v in mundo.viagens),
                    "transferencia": sum(v.tipo != "DIST" for v in mundo.viagens)},
        "entregas_por_viagem_media": round(len(mundo.entregas) / len(mundo.viagens), 2),
        "ctes": {"emitidos": n_ctes_emitidos, **xmls,
                 "multi_pedido": por_tipo["cte_multi_pedido"],
                 "pct_multi_pedido": round(100 * por_tipo["cte_multi_pedido"] / n_ctes_emitidos, 2),
                 "pct_cancelado": round(100 * por_tipo["cte_cancelado"] / n_ctes_emitidos, 2),
                 "pct_duplicado": round(100 * por_tipo["cte_duplicado"] / n_ctes_emitidos, 2)},
        "anomalias": dict(sorted(por_tipo.items())),
        "anomalias_pct_entregas_normais": {
            k: round(100 * por_tipo[k] / entregas_normais, 2)
            for k in ("entrega_atrasada", "entrega_incompleta", "entrega_sem_data")},
        "caso_explicavel": [{"cte": c.chave, "tipo": c.caso_explicavel, "pedidos": [p.id for p in c.pedidos],
                             "vTPrest": str(c.vTPrest), "cancelado": c.cancelado, "duplicado": c.duplicado}
                            for c in ctes if c.caso_explicavel],
    }
    (meta / "contagens.json").write_text(json.dumps(contagens, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return contagens


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--empresa")
    group.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)
    empresas = config.empresas_disponiveis() if args.all else [args.empresa]
    for empresa in empresas:
        c = generate(empresa)
        print(f"[ok] {empresa}: {c['tabelas']['erp_pedidos']} pedidos, {c['viagens']['total']} viagens, "
              f"{c['ctes']['xml_total']} XML")
    return 0


if __name__ == "__main__":
    sys.exit(main())
