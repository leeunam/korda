"""Escrita das fontes "sujas": CSV por sistema (nomes de coluna e formato da empresa) e XML de CT-e."""

from __future__ import annotations

import csv
import datetime as dt
from collections import Counter
from pathlib import Path

import cte_xml
from anomalies import Cte
from model import Mundo, cnpj_ficticio


class CsvFormat:
    def __init__(self, cfg: dict):
        fmt = cfg["formato"]
        self.sep = fmt["csv"]["separador"]
        self.decimal = fmt["csv"]["decimal"]
        self.data = fmt["data"]
        self.data_hora = fmt["data_hora_tms"]
        self.mistos = fmt["formatos_mistos"]

    def num(self, value, casas: int) -> str:
        text = f"{float(value):.{casas}f}"
        return text.replace(".", self.decimal) if self.decimal != "." else text


def _write(path: Path, colunas: dict, logical_rows: list[dict], fmt: CsvFormat) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    campos = [c for c in colunas if any(c in r for r in logical_rows)]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=fmt.sep, lineterminator="\n")
        writer.writerow([colunas[c] for c in campos])
        for row in logical_rows:
            writer.writerow([row.get(c, "") for c in campos])


def write_csvs(mundo: Mundo, out: Path) -> dict[str, int]:
    cfg = mundo.ctx.cfg
    fmt = CsvFormat(cfg)
    col = cfg["colunas"]
    prazo_em_dias = cfg["pedido"]["campo_prazo"] == "prazo_dias"

    clientes = [{"id": c.id, "razao": c.razao, "cnpj": c.cnpj, "municipio_ibge": c.municipio.codigo_ibge,
                 "ativo": "S"} for c in mundo.clientes]
    pedidos = []
    for p in sorted(mundo.pedidos, key=lambda p: p.id):
        row = {"id": p.id, "cliente_id": p.cliente.id, "dt_emissao": p.dt_emissao.strftime(fmt.data),
               "qt_itens": p.qt_itens, "peso_kg": fmt.num(p.peso_kg, 1), "volume_m3": fmt.num(p.volume_m3, 3),
               "valor_mercadoria": fmt.num(p.valor, 2), "chave_nfe": p.chave_nfe}
        if prazo_em_dias:
            row["prazo_dias"] = p.prazo_dias
        else:
            row["dt_prevista"] = p.dt_prevista.strftime(fmt.data)
        pedidos.append(row)
    veiculos = [{"id": v.id, "placa": v.placa, "tipo": v.tipo, "cap_kg": fmt.num(v.cap_kg, 0),
                 "cap_m3": fmt.num(v.cap_m3, 1)} for v in mundo.veiculos]
    viagens = [{"id": v.id, "veiculo_id": v.veiculo.id, "dt_saida": v.dt_saida.strftime(fmt.data_hora),
                "km": fmt.num(v.km, 1), "tipo": v.tipo} for v in mundo.viagens]
    entregas = []
    for e in mundo.entregas:
        if e.dt_realizada is None:
            quando = ""
        elif e.formato_misto is not None:
            quando = e.dt_realizada.strftime(fmt.mistos[e.formato_misto])
        else:
            quando = e.dt_realizada.strftime(fmt.data_hora)
        entregas.append({"id": e.id, "viagem_id": e.viagem_id, "pedido_id": e.pedido.id, "seq": e.seq,
                         "qt_entregue": e.qt_entregue, "dt_realizada": quando, "status": e.status})

    _write(out / "erp" / "erp_clientes.csv", col["erp_clientes"], clientes, fmt)
    _write(out / "erp" / "erp_pedidos.csv", col["erp_pedidos"], pedidos, fmt)
    _write(out / "tms" / "tms_veiculos.csv", col["tms_veiculos"], veiculos, fmt)
    _write(out / "tms" / "tms_viagens.csv", col["tms_viagens"], viagens, fmt)
    _write(out / "tms" / "tms_entregas.csv", col["tms_entregas"], entregas, fmt)
    return {"erp_clientes": len(clientes), "erp_pedidos": len(pedidos), "tms_veiculos": len(veiculos),
            "tms_viagens": len(viagens), "tms_entregas": len(entregas)}


def _iso(moment: dt.datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S") + "-03:00"


def write_ctes(mundo: Mundo, ctes: list[Cte], out: Path) -> dict[str, int]:
    folder = out / "cte"
    folder.mkdir(parents=True, exist_ok=True)
    sede = mundo.ctx.sede
    emp = mundo.ctx.cfg["empresa"]
    emit = {"cnpj": cnpj_ficticio(emp["cnpj_base"]), "ie": emp["ie"], "rntrc": f"{int(emp['cnpj_base']) % 10**8:08d}",
            "logradouro": "Rodovia Ficticia km 10", "numero": "1000", "bairro": "Distrito Industrial",
            "cod_mun": sede.codigo_ibge, "municipio": sede.nome, "cep": "13000000", "uf": sede.uf}
    sede_d = {"cod_mun": sede.codigo_ibge, "municipio": sede.nome, "uf": sede.uf}
    counts: Counter = Counter()
    for c in ctes:
        cli = c.pedidos[0].cliente
        pessoa = {"logradouro": cli.logradouro, "numero": cli.numero, "bairro": cli.bairro,
                  "cod_mun": cli.municipio.codigo_ibge, "municipio": cli.municipio.nome, "cep": cli.cep,
                  "uf": cli.municipio.uf}
        rem = dict(pessoa, cnpj=cli.cnpj, ie=cli.ie, nome=cli.razao)
        dest = dict(pessoa, cnpj=cnpj_ficticio(f"{(cli.id * 7919) % 10**8:08d}", 2), ie=cli.ie[::-1],
                    nome=f"Destinatario Final {cli.id} (ficticio)")
        doc = {"chave": c.chave, "serie": 1, "numero": c.numero, "dh_emissao": _iso(c.dh_emissao),
               "vTPrest": c.vTPrest, "valor_carga": sum(p.valor for p in c.pedidos),
               "peso_kg": sum(p.peso_kg for p in c.pedidos), "volume_m3": sum(p.volume_m3 for p in c.pedidos),
               "chaves_nfe": [p.chave_nfe for p in c.pedidos], "protocolo": c.protocolo}
        xml = cte_xml.cte_proc(doc, emit, rem, dest, sede_d)
        (folder / f"{c.chave}-cte.xml").write_bytes(xml)
        counts["xml_cte"] += 1
        if c.duplicado:
            (folder / f"{c.chave}-cte_reenvio.xml").write_bytes(xml)
            counts["xml_cte_duplicado"] += 1
        if c.cancelado:
            ev = cte_xml.proc_evento_cancelamento(c.chave, emit["cnpj"], c.protocolo, c.evento["protocolo"],
                                                  _iso(c.evento["dh"]), c.evento["justificativa"])
            (folder / f"{c.chave}-canc-110111.xml").write_bytes(ev)
            counts["xml_evento_cancelamento"] += 1
    counts["xml_total"] = counts["xml_cte"] + counts["xml_cte_duplicado"] + counts["xml_evento_cancelamento"]
    return dict(counts)
