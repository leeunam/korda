"""Particiona as fontes de uma empresa por dia, para o replay dos sistemas simulados.

Uso (na imagem korda-simulados, sem rede):
    python -m korda_simulados.preparar --fontes /work/fontes --empresa /work/empresa.yaml --saida /work/saida

Lê os CSV e XML gerados e o `empresa.yaml` (o cliente conhece o próprio sistema). Nunca lê
`_gerador/`. Produz:

    saida/catalogo.json                    dias, tabelas, colunas físicas, tipos, mudança de esquema
    saida/dias/<AAAA-MM-DD>/erp/<t>.csv    linhas do ERP já tipadas (ISO, ponto decimal) para o COPY
    saida/dias/<AAAA-MM-DD>/tms/<t>.jsonl  registros da API com `atualizado_em`
    saida/dias/<AAAA-MM-DD>/cte/*.xml      cópia byte a byte dos XML do dia
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import yaml

from . import ROTULO, __version__
from .esquema import CAMPO_ATUALIZACAO, CHAVE, ERP, RECURSOS, TMS, ErroEsquema, data, data_hora, valor_erp, valor_tms

NS_CTE = "{http://www.portalfiscal.inf.br/cte}"


def _ler_csv(caminho: Path, sep: str) -> tuple[list[str], list[dict]]:
    with caminho.open(encoding="utf-8", newline="") as f:
        leitor = csv.DictReader(f, delimiter=sep)
        return list(leitor.fieldnames or []), list(leitor)


def _dia_cte(xml: bytes) -> str:
    raiz = ET.fromstring(xml)
    for caminho in (f".//{NS_CTE}ide/{NS_CTE}dhEmi", f".//{NS_CTE}infEvento/{NS_CTE}dhEvento"):
        el = raiz.find(caminho)
        if el is not None and el.text:
            return el.text[:10]
    raise ErroEsquema("XML sem dhEmi nem dhEvento")


def preparar(fontes: Path, empresa_yaml: Path, saida: Path, mudanca: str | None = "ultimo",
             renomear: str | None = None) -> dict:
    cfg = yaml.safe_load(empresa_yaml.read_text(encoding="utf-8"))
    fmt = cfg["formato"]
    sep = fmt["csv"]["separador"]
    colunas_cfg = cfg["colunas"]
    if saida.exists() and any(saida.iterdir()):
        raise ErroEsquema(f"saída não está vazia: {saida}")

    # 1) Ler tabelas e descobrir colunas físicas presentes.
    tabelas: dict[str, tuple[list[str], list[dict], dict[str, str]]] = {}
    for sistema, esquemas in (("erp", ERP), ("tms", TMS)):
        for tabela in esquemas:
            fis_para_log = {v: k for k, v in colunas_cfg[tabela].items()}
            cabecalho, linhas = _ler_csv(fontes / sistema / f"{tabela}.csv", sep)
            desconhecidas = [c for c in cabecalho if c not in fis_para_log]
            if desconhecidas:
                raise ErroEsquema(f"{tabela}: colunas fora de empresa.yaml: {desconhecidas}")
            tabelas[tabela] = (cabecalho, linhas, fis_para_log)

    def fis(tabela: str, logica: str) -> str:
        return colunas_cfg[tabela][logica]

    # 2) Dia de cada registro.
    dia_viagem = {}
    for r in tabelas["tms_viagens"][1]:
        dia_viagem[r[fis("tms_viagens", "id")]] = data_hora(r[fis("tms_viagens", "dt_saida")], fmt["data_hora_tms"]).date().isoformat()
    dias_registro: dict[str, list[str]] = {
        "erp_pedidos": [data(r[fis("erp_pedidos", "dt_emissao")], fmt["data"]).isoformat()
                        for r in tabelas["erp_pedidos"][1]],
        "tms_viagens": [dia_viagem[r[fis("tms_viagens", "id")]] for r in tabelas["tms_viagens"][1]],
        "tms_entregas": [dia_viagem[r[fis("tms_entregas", "viagem_id")]] for r in tabelas["tms_entregas"][1]],
    }
    xmls = sorted((fontes / "cte").glob("*.xml"))
    dia_xml = {p.name: _dia_cte(p.read_bytes()) for p in xmls}
    todos_dias = sorted({d for ds in dias_registro.values() for d in ds} | set(dia_xml.values()))
    primeiro = todos_dias[0]
    for cadastro in ("erp_clientes", "tms_veiculos"):  # cadastros já existem no primeiro dia
        dias_registro[cadastro] = [primeiro] * len(tabelas[cadastro][1])

    # 3) Escrever partições.
    contagens: dict = {"erp": defaultdict(dict), "tms": defaultdict(dict), "cte": defaultdict(int)}
    catalogo_erp, catalogo_tms = {}, {}
    for tabela, tipos in ERP.items():
        cabecalho, linhas, f2l = tabelas[tabela]
        catalogo_erp[tabela] = {"colunas": [[c, tipos[f2l[c]]] for c in cabecalho], "chave": fis(tabela, CHAVE)}
        por_dia = defaultdict(list)
        for r, d in zip(linhas, dias_registro[tabela]):
            por_dia[d].append([valor_erp(tipos[f2l[c]], r[c], fmt) for c in cabecalho])
        for d, regs in por_dia.items():
            destino = saida / "dias" / d / "erp" / f"{tabela}.csv"
            destino.parent.mkdir(parents=True, exist_ok=True)
            with destino.open("w", encoding="utf-8", newline="") as f:
                w = csv.writer(f, lineterminator="\n")
                w.writerow(cabecalho)
                w.writerows(regs)
            contagens["erp"][tabela][d] = len(regs)
    for tabela, tipos in TMS.items():
        cabecalho, linhas, f2l = tabelas[tabela]
        catalogo_tms[tabela] = {"recurso": RECURSOS[tabela], "colunas": cabecalho, "chave": fis(tabela, CHAVE)}
        por_dia = defaultdict(list)
        for r, d in zip(linhas, dias_registro[tabela]):
            obj = {c: valor_tms(tipos[f2l[c]], r[c], fmt) for c in cabecalho}
            obj[CAMPO_ATUALIZACAO] = f"{d}T23:00:00-03:00"
            por_dia[d].append(obj)
        for d, regs in por_dia.items():
            destino = saida / "dias" / d / "tms" / f"{tabela}.jsonl"
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in regs), encoding="utf-8")
            contagens["tms"][tabela][d] = len(regs)
    for p in xmls:
        d = dia_xml[p.name]
        destino = saida / "dias" / d / "cte" / p.name
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(p.read_bytes())
        contagens["cte"][d] += 1

    # 4) Mudança de esquema (genérica): uma coluna da API renomeada a partir de um dia.
    mudanca_esquema = None
    if mudanca:
        tabela, logica = "tms_entregas", "dt_realizada"
        coluna = fis(tabela, logica)
        novo = renomear or f"{coluna}_v2"
        a_partir_de = todos_dias[-1] if mudanca == "ultimo" else mudanca
        if a_partir_de not in todos_dias:
            raise ErroEsquema(f"dia da mudança fora do período: {a_partir_de}")
        mudanca_esquema = {"sistema": "tms", "tabela": tabela, "coluna": coluna, "novo_nome": novo,
                           "a_partir_de": a_partir_de}

    catalogo = {
        "rotulo": ROTULO,
        "versao": __version__,
        "empresa_id": cfg.get("empresa_id"),
        "dias": todos_dias,
        "erp": catalogo_erp,
        "tms": catalogo_tms,
        "campo_atualizacao": CAMPO_ATUALIZACAO,
        "mudanca_esquema": mudanca_esquema,
        "contagens": {k: (dict(v) if k == "cte" else {t: dict(x) for t, x in v.items()})
                      for k, v in contagens.items()},
    }
    saida.mkdir(parents=True, exist_ok=True)
    (saida / "catalogo.json").write_text(json.dumps(catalogo, ensure_ascii=False, indent=1) + "\n",
                                         encoding="utf-8")
    return catalogo


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Particiona as fontes por dia para o replay.")
    p.add_argument("--fontes", type=Path, required=True)
    p.add_argument("--empresa", type=Path, required=True, help="empresa.yaml")
    p.add_argument("--saida", type=Path, required=True)
    p.add_argument("--mudanca", default="ultimo", help="dia da mudança de esquema (AAAA-MM-DD), 'ultimo' ou 'nenhuma'")
    p.add_argument("--renomear", default=None, help="novo nome da coluna (padrão: <coluna>_v2)")
    a = p.parse_args(argv)
    try:
        cat = preparar(a.fontes, a.empresa, a.saida, None if a.mudanca == "nenhuma" else a.mudanca, a.renomear)
    except ErroEsquema as e:
        print(f"preparo recusado: {e}", file=sys.stderr)
        return 1
    print(json.dumps({"dias": len(cat["dias"]), "primeiro": cat["dias"][0], "ultimo": cat["dias"][-1],
                      "mudanca_esquema": cat["mudanca_esquema"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
