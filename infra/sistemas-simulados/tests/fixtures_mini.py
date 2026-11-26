"""Mini empresa sintética para os testes unitários (escrita à mão; não usa o gerador)."""

from pathlib import Path

NS = "http://www.portalfiscal.inf.br/cte"

EMPRESA_YAML = """
empresa_id: 99_teste
formato:
  csv: {separador: ";", decimal: ",", encoding: utf-8}
  data: "%Y-%m-%d"
  data_hora_tms: "%Y-%m-%d %H:%M"
colunas:
  erp_clientes: {id: cd_cli, razao: ds_razao, cnpj: nr_cnpj, municipio_ibge: cd_mun, ativo: fl_ativo}
  erp_pedidos: {id: cd_ped, cliente_id: cd_cli, dt_emissao: dt_emis, dt_prevista: dt_prev, prazo_dias: prz, qt_itens: qt_itens, peso_kg: ps_bruto, volume_m3: vl_cubag, valor_mercadoria: vl_merc, chave_nfe: ch_nfe}
  tms_veiculos: {id: id_veic, placa: placa, tipo: tp_veic, cap_kg: cap_kg, cap_m3: cap_m3}
  tms_viagens: {id: id_viag, veiculo_id: id_veic, dt_saida: dt_saida, km: km, tipo: tp_viag}
  tms_entregas: {id: id_ent, viagem_id: id_viag, pedido_id: nr_ped, seq: seq, qt_entregue: qt_ent, dt_realizada: dt_baixa, status: st_ent}
"""

CSVS = {
    "erp/erp_clientes.csv": "cd_cli;ds_razao;nr_cnpj;cd_mun;fl_ativo\n1;Cliente A (fictício);00000000000100;3509502;S\n",
    "erp/erp_pedidos.csv": (
        "cd_ped;cd_cli;dt_emis;dt_prev;qt_itens;ps_bruto;vl_cubag;vl_merc;ch_nfe\n"
        "10;1;2026-09-01;2026-09-02;5;363,9;2,188;100,00;NFE10\n"
        "11;1;2026-09-02;2026-09-03;3;12,0;0,5;50,50;NFE11\n"
    ),
    "tms/tms_veiculos.csv": "id_veic;placa;tp_veic;cap_kg;cap_m3\nV01;KRD0A00;VUC;3000;16,0\n",
    "tms/tms_viagens.csv": "id_viag;id_veic;dt_saida;km;tp_viag\n50;V01;2026-09-02 07:48;261,7;DIST\n51;V01;2026-09-03 07:30;10,0;DIST\n",
    "tms/tms_entregas.csv": (
        "id_ent;id_viag;nr_ped;seq;qt_ent;dt_baixa;st_ent\n"
        "70;50;10;1;5;2026-09-02 08:33;ENTREGUE\n"
        "71;51;11;1;2;03/09/26;PARCIAL\n"
        "72;51;11;2;1;;ENTREGUE\n"
    ),
}


def cte(chave: str, dh: str) -> bytes:
    return (f'<cteProc xmlns="{NS}"><CTe><infCte Id="CTe{chave}"><ide><dhEmi>{dh}</dhEmi></ide>'
            f'</infCte></CTe></cteProc>').encode()


def evento(chave: str, dh: str) -> bytes:
    return (f'<procEventoCTe xmlns="{NS}"><eventoCTe><infEvento><chCTe>{chave}</chCTe>'
            f'<dhEvento>{dh}</dhEvento></infEvento></eventoCTe></procEventoCTe>').encode()


def escrever(raiz: Path) -> tuple[Path, Path]:
    fontes = raiz / "fontes"
    for rel, texto in CSVS.items():
        (fontes / rel).parent.mkdir(parents=True, exist_ok=True)
        (fontes / rel).write_text(texto, encoding="utf-8")
    (fontes / "cte").mkdir()
    (fontes / "cte" / "A-cte.xml").write_bytes(cte("A", "2026-09-02T05:30:00-03:00"))
    (fontes / "cte" / "A-cte_reenvio.xml").write_bytes(cte("A", "2026-09-02T05:30:00-03:00"))
    (fontes / "cte" / "A-canc.xml").write_bytes(evento("A", "2026-09-03T06:40:00-03:00"))
    (fontes / "_gerador").mkdir()
    (fontes / "_gerador" / "segredo.csv").write_text("nao ler\n")
    yaml_ = raiz / "empresa.yaml"
    yaml_.write_text(EMPRESA_YAML, encoding="utf-8")
    return fontes, yaml_
