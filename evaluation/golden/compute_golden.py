"""Gabarito independente dos três KPIs a partir das fontes brutas geradas.

Uso:
    .venv/bin/python evaluation/golden/compute_golden.py --all
    .venv/bin/python evaluation/golden/compute_golden.py --empresa 01_demo [--fontes <dir>]

INDEPENDÊNCIA: este módulo NÃO importa nada de data/synthetic/generator e não lê
output/<empresa>/_gerador/. Ele lê só o que um cliente entregaria (CSV de ERP/TMS e
XML de CT-e) e, do empresa.yaml, apenas formato, nomes de coluna e regras_referencia.
As regras são PROPOSTA pendente de K02 (ver regras_referencia.status).

Saída em evaluation/golden/<empresa>/:
    kpis.json        valores agregados, regras usadas e contagens
    por_pedido.csv   custo rateado, prazo, realizado, no prazo, completo, OTIF
    por_viagem.csv   carga, capacidade, ocupação, custo total e por entrega
    fontes.sha256    checksum de cada arquivo de entrada usado
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import yaml

GOLDEN = Path(__file__).resolve().parent
ROOT = GOLDEN.parents[1]
EMPRESAS = ROOT / "data" / "synthetic" / "empresas"
FONTES = ROOT / "data" / "synthetic" / "output"
NS = {"c": "http://www.portalfiscal.inf.br/cte"}

# Padrões de data/hora aceitos pelo gabarito (lista própria, não importada do gerador).
PADROES_DATA_HORA = ["%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%d/%m/%y",
                     "%d.%m.%Y", "%Y-%m-%d"]

CORRECOES = ("deduplicar_cte", "excluir_cancelados", "ratear", "completude", "pontualidade",
             "sem_data", "datas_mistas", "excluir_tipos_viagem", "unidade_ocupacao", "sabado")


@dataclass
class Fontes:
    pedidos: dict[str, dict]
    veiculos: dict[str, dict]
    viagens: dict[str, dict]
    entregas: list[dict]
    ctes: list[dict]              # um item por ARQUIVO cteProc (duplicatas aparecem 2x)
    cancelados: set[str]          # chaves com cancelamento homologado (110111, cStat 135)
    arquivos: list[Path] = field(default_factory=list)


# ------------------------------------------------------------------ leitura


def _num(text: str, decimal: str) -> float:
    return float(text.replace(decimal, ".")) if decimal != "." else float(text)


def _read_csv(path: Path, sep: str, nomes: dict[str, str]) -> list[dict]:
    inverso = {fisico: logico for logico, fisico in nomes.items()}
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=sep)
        faltando = set(reader.fieldnames or []) - set(inverso)
        if faltando:
            raise ValueError(f"{path.name}: colunas sem mapeamento {sorted(faltando)}")
        return [{inverso[k]: v for k, v in row.items()} for row in reader]


def load_fontes(cfg: dict, pasta: Path) -> Fontes:
    sep, dec = cfg["formato"]["csv"]["separador"], cfg["formato"]["csv"]["decimal"]
    col = cfg["colunas"]
    pedidos = {}
    for r in _read_csv(pasta / "erp" / "erp_pedidos.csv", sep, col["erp_pedidos"]):
        r["peso_kg"], r["volume_m3"] = _num(r["peso_kg"], dec), _num(r["volume_m3"], dec)
        r["valor_mercadoria"] = _num(r["valor_mercadoria"], dec)
        r["qt_itens"] = int(r["qt_itens"])
        pedidos[r["id"]] = r
    veiculos = {}
    for r in _read_csv(pasta / "tms" / "tms_veiculos.csv", sep, col["tms_veiculos"]):
        r["cap_kg"], r["cap_m3"] = _num(r["cap_kg"], dec), _num(r["cap_m3"], dec)
        veiculos[r["id"]] = r
    viagens = {r["id"]: r for r in _read_csv(pasta / "tms" / "tms_viagens.csv", sep, col["tms_viagens"])}
    entregas = _read_csv(pasta / "tms" / "tms_entregas.csv", sep, col["tms_entregas"])
    for r in entregas:
        r["qt_entregue"] = int(r["qt_entregue"])

    ctes, cancelados = [], set()
    xmls = sorted((pasta / "cte").glob("*.xml"))
    for path in xmls:
        root = ET.parse(path).getroot()
        tag = root.tag.split("}")[1]
        if tag == "cteProc":
            stat = root.findtext("c:protCTe/c:infProt/c:cStat", namespaces=NS)
            ctes.append({
                "arquivo": path.name,
                "chave": root.findtext("c:protCTe/c:infProt/c:chCTe", namespaces=NS),
                "autorizado": stat == "100",
                "vTPrest": float(root.findtext(".//c:vPrest/c:vTPrest", namespaces=NS)),
                "nfes": [e.text for e in root.findall(".//c:infDoc/c:infNFe/c:chave", namespaces=NS)],
            })
        elif tag == "procEventoCTe":
            tipo = root.findtext("c:eventoCTe/c:infEvento/c:tpEvento", namespaces=NS)
            stat = root.findtext("c:retEventoCTe/c:infEvento/c:cStat", namespaces=NS)
            if tipo == "110111" and stat in ("135", "136"):
                cancelados.add(root.findtext("c:eventoCTe/c:infEvento/c:chCTe", namespaces=NS))
        else:
            raise ValueError(f"{path.name}: raiz inesperada {tag}")
    arquivos = sorted([*pasta.glob("erp/*.csv"), *pasta.glob("tms/*.csv"), *xmls])
    return Fontes(pedidos, veiculos, viagens, entregas, ctes, cancelados, arquivos)


# ------------------------------------------------------------------ regras


def parse_data_hora(texto: str, principal: str, todos: bool) -> dt.datetime | None:
    """Converte dt_realizada. Com todos=False só aceita o formato principal (comportamento ingênuo)."""
    if not texto:
        return None
    padroes = PADROES_DATA_HORA if todos else [principal]
    for padrao in padroes:
        try:
            return dt.datetime.strptime(texto, padrao)
        except ValueError:
            continue
    if todos:
        raise ValueError(f"data não reconhecida: {texto!r}")
    return None


def dia_util(d: dt.date, sabado: bool) -> bool:
    return d.weekday() < 5 or (sabado and d.weekday() == 5)


def somar_dias_uteis(d: dt.date, n: int, sabado: bool) -> dt.date:
    while n > 0:
        d += dt.timedelta(days=1)
        if dia_util(d, sabado):
            n -= 1
    return d


def compute(cfg: dict, f: Fontes, desligar: frozenset[str] = frozenset()) -> dict:
    """Calcula KPIs e detalhamentos. `desligar` lista correções substituídas pelo comportamento ingênuo."""
    on = lambda nome: nome not in desligar  # noqa: E731
    regras = cfg["regras_referencia"]
    fmt = cfg["formato"]

    excluir_tipos = set(regras["excluir_tipos_viagem"]) if on("excluir_tipos_viagem") else set()
    sem_data = regras["sem_data_realizada"]
    if not on("sem_data"):
        sem_data = "excluir" if sem_data == "falha" else "falha"
    unidade = regras["ocupacao_unidade"]
    if not on("unidade_ocupacao"):
        unidade = "kg" if unidade == "m3" else "m3"
    sabado = regras["prazo_conta_sabado"] if on("sabado") else not regras["prazo_conta_sabado"]
    criterio = {"peso": "peso_kg", "volume": "volume_m3", "valor": "valor_mercadoria"}[regras["rateio_cte"]]

    # --- CT-e considerados
    ctes = f.ctes
    if on("deduplicar_cte"):
        vistos, unicos = set(), []
        for c in ctes:
            if c["chave"] not in vistos:
                vistos.add(c["chave"])
                unicos.append(c)
        ctes = unicos
    ctes = [c for c in ctes if c["autorizado"]]
    if on("excluir_cancelados"):
        ctes = [c for c in ctes if c["chave"] not in f.cancelados]

    pedido_por_nfe = {p["chave_nfe"]: pid for pid, p in f.pedidos.items()}
    custo = {pid: 0.0 for pid in f.pedidos}
    ctes_do_pedido: dict[str, list[str]] = {pid: [] for pid in f.pedidos}
    for c in ctes:
        pids = [pedido_por_nfe[n] for n in c["nfes"]]
        base = sum(f.pedidos[p][criterio] for p in pids)
        for p in pids:
            parte = c["vTPrest"] * f.pedidos[p][criterio] / base if on("ratear") else c["vTPrest"]
            custo[p] += parte
            ctes_do_pedido[p].append(c["chave"])

    # --- entregas
    por_pedido, por_viagem = [], {}
    custo_total = n_custo = 0
    otif_num = otif_den = 0
    for e in f.entregas:
        viagem = f.viagens[e["viagem_id"]]
        p = f.pedidos[e["pedido_id"]]
        elegivel = viagem["tipo"] not in excluir_tipos
        if "dt_prevista" in p and p["dt_prevista"]:
            prevista = dt.datetime.strptime(p["dt_prevista"], fmt["data"]).date()
        else:
            emissao = dt.datetime.strptime(p["dt_emissao"], fmt["data"]).date()
            prevista = somar_dias_uteis(emissao, int(p["prazo_dias"]), sabado)
        realizada = parse_data_hora(e["dt_realizada"], fmt["data_hora_tms"], todos=on("datas_mistas"))
        completo = e["qt_entregue"] >= p["qt_itens"] if on("completude") else True
        if realizada is None and e["dt_realizada"]:
            # ingênuo (datas_mistas desligada): texto presente mas não convertido; a comparação com
            # nulo resulta falsa e a entrega conta como fora do prazo
            no_prazo = False
            conta_otif = elegivel
        elif realizada is None:
            no_prazo = False
            conta_otif = elegivel and sem_data == "falha"
        else:
            no_prazo = realizada.date() <= prevista if on("pontualidade") else True
            conta_otif = elegivel
        otif = conta_otif and no_prazo and completo
        if conta_otif:
            otif_den += 1
            otif_num += otif
        # custo por entrega: só pedidos cobertos por algum CT-e considerado
        # (pedido de CT-e cancelado e não reemitido sai do denominador)
        elegivel_custo = elegivel and bool(ctes_do_pedido[p["id"]])
        if elegivel_custo:
            custo_total += custo[p["id"]]
            n_custo += 1
        por_pedido.append({"pedido_id": p["id"], "viagem_id": viagem["id"], "tipo_viagem": viagem["tipo"],
                           "elegivel_custo": int(elegivel_custo), "custo_frete_rateado": round(custo[p["id"]], 2),
                           "ctes": "+".join(ctes_do_pedido[p["id"]]), "data_prevista": prevista.isoformat(),
                           "data_realizada": realizada.date().isoformat() if realizada else "",
                           "elegivel_otif": int(conta_otif), "no_prazo": int(no_prazo), "completo": int(completo),
                           "otif": int(otif)})
        v = por_viagem.setdefault(viagem["id"], {"viagem_id": viagem["id"], "veiculo_id": viagem["veiculo_id"],
                                                 "tipo_viagem": viagem["tipo"], "n_entregas": 0, "carga": 0.0,
                                                 "custo_frete_total": 0.0})
        v["n_entregas"] += 1
        v["carga"] += p["peso_kg"] if unidade == "kg" else p["volume_m3"]
        v["custo_frete_total"] += custo[p["id"]]

    carga_total = cap_total = 0.0
    for v in por_viagem.values():
        veic = f.veiculos[v["veiculo_id"]]
        v["capacidade"] = veic["cap_kg"] if unidade == "kg" else veic["cap_m3"]
        v["unidade"] = unidade
        v["ocupacao"] = round(v["carga"] / v["capacidade"], 4)
        v["acima_capacidade"] = int(v["carga"] > v["capacidade"])
        v["custo_por_entrega"] = round(v["custo_frete_total"] / v["n_entregas"], 2)
        v["carga"] = round(v["carga"], 3)
        v["custo_frete_total"] = round(v["custo_frete_total"], 2)
        carga_total += v["carga"]
        cap_total += v["capacidade"]

    return {
        "kpis": {
            "custo_frete_por_entrega": round(custo_total / n_custo, 4),
            "otif_pct": round(100 * otif_num / otif_den, 4),
            "ocupacao_pct": round(100 * carga_total / cap_total, 4),
        },
        "contagens": {"entregas_elegiveis_custo": n_custo, "frete_total_elegivel": round(custo_total, 2),
                      "pedidos_otif_denominador": otif_den, "pedidos_otif": otif_num,
                      "viagens": len(por_viagem), "ctes_considerados": len(ctes),
                      "ctes_cancelados": len(f.cancelados), "arquivos_cte": len(f.ctes)},
        "por_pedido": por_pedido,
        "por_viagem": list(por_viagem.values()),
    }


# ------------------------------------------------------------------ saída


def sha256_lines(arquivos: list[Path], base: Path) -> str:
    linhas = []
    for path in arquivos:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        linhas.append(f"{digest}  {path.relative_to(base).as_posix()}")
    return "\n".join(linhas) + "\n"


def write_outputs(empresa: str, cfg: dict, f: Fontes, res: dict, pasta_fontes: Path) -> Path:
    out = GOLDEN / empresa
    out.mkdir(parents=True, exist_ok=True)
    kpis = {"empresa_id": empresa, "uso": cfg["uso"], "status": "RASCUNHO: regras_referencia pendentes de K02",
            "regras_referencia": cfg["regras_referencia"], **{k: res[k] for k in ("kpis", "contagens")}}
    (out / "kpis.json").write_text(json.dumps(kpis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for nome, linhas in (("por_pedido.csv", res["por_pedido"]), ("por_viagem.csv", res["por_viagem"])):
        with (out / nome).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(linhas[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(sorted(linhas, key=lambda r: int(r.get("pedido_id", r.get("viagem_id")))))
    (out / "fontes.sha256").write_text(sha256_lines(f.arquivos, pasta_fontes), encoding="utf-8")
    return out


def load_cfg(empresa: str) -> dict:
    return yaml.safe_load((EMPRESAS / empresa / "empresa.yaml").read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--empresa")
    group.add_argument("--all", action="store_true")
    parser.add_argument("--fontes", type=Path, default=FONTES, help="pasta com <empresa>/{erp,tms,cte}")
    args = parser.parse_args(argv)
    empresas = sorted(p.name for p in EMPRESAS.iterdir() if (p / "empresa.yaml").is_file()) if args.all else [args.empresa]
    for empresa in empresas:
        cfg = load_cfg(empresa)
        pasta = args.fontes / empresa
        fontes = load_fontes(cfg, pasta)
        res = compute(cfg, fontes)
        write_outputs(empresa, cfg, fontes, res, pasta)
        k = res["kpis"]
        print(f"[ok] {empresa}: custo/entrega R$ {k['custo_frete_por_entrega']:.2f} | "
              f"OTIF {k['otif_pct']:.2f}% | ocupação {k['ocupacao_pct']:.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
