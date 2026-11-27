"""Gabarito: valores conferidos à mão, sem usar o gerador."""

import datetime as dt
from copy import deepcopy
from decimal import Decimal
from io import StringIO
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

GOLDEN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GOLDEN))

import compute_golden as cg  # noqa: E402
import sensitivity  # noqa: E402

CFG = {
    "formato": {"data": "%Y-%m-%d", "data_hora_tms": "%Y-%m-%d %H:%M"},
    "regras_referencia": {"rateio_cte": "peso", "sem_data_realizada": "falha", "ocupacao_unidade": "kg",
                          "prazo_conta_sabado": True, "excluir_tipos_viagem": []},
}


def exemplo_quatro_linhas() -> cg.Fontes:
    """Exemplo do contexto do Gabriel: A1=300 (duplicado), B2=200, C3=150 (cancelado, sem reemissão).
    P1 (100 kg) e P2 (200 kg) no A1; P3 (50 kg) no B2; P4 (80 kg) no C3."""
    pedidos = {}
    for pid, kg in (("P1", 100), ("P2", 200), ("P3", 50), ("P4", 80)):
        pedidos[pid] = {"id": pid, "chave_nfe": f"NF{pid}", "peso_kg": kg, "volume_m3": kg / 100,
                        "valor_mercadoria": kg * 10, "qt_itens": 1, "dt_prevista": "2026-09-02"}
    ctes = [
        {"arquivo": "a1.xml", "chave": "A1", "autorizado": True, "vTPrest": 300.0, "nfes": ["NFP1", "NFP2"]},
        {"arquivo": "a1_copia.xml", "chave": "A1", "autorizado": True, "vTPrest": 300.0, "nfes": ["NFP1", "NFP2"]},
        {"arquivo": "b2.xml", "chave": "B2", "autorizado": True, "vTPrest": 200.0, "nfes": ["NFP3"]},
        {"arquivo": "c3.xml", "chave": "C3", "autorizado": True, "vTPrest": 150.0, "nfes": ["NFP4"]},
    ]
    entregas = [{"id": i, "viagem_id": "V1", "pedido_id": pid, "qt_entregue": 1,
                 "dt_realizada": "2026-09-02 10:00"} for i, pid in enumerate(pedidos)]
    return cg.Fontes(pedidos, {"C1": {"cap_kg": 1000.0, "cap_m3": 10.0}},
                     {"V1": {"id": "V1", "veiculo_id": "C1", "tipo": "DIST"}}, entregas, ctes, {"C3"})


class ExemploQuatroLinhasTest(unittest.TestCase):
    def setUp(self):
        self.res = cg.compute(CFG, exemplo_quatro_linhas())
        self.custo = {r["pedido_id"]: r["custo_frete_rateado"] for r in self.res["por_pedido"]}

    def test_custo_por_entrega_correto_e_166_67(self):
        # 500 / 3 = 166,67 (A1 deduplicado, C3 e P4 fora, A1 rateado por peso)
        self.assertAlmostEqual(self.res["kpis"]["custo_frete_por_entrega"], 166.6667, places=4)

    def test_rateio_por_peso_de_a1(self):
        self.assertEqual((self.custo["P1"], self.custo["P2"], self.custo["P3"]), (100.0, 200.0, 200.0))

    def test_pedido_de_cte_cancelado_sem_reemissao_sai_do_custo(self):
        linha = next(r for r in self.res["por_pedido"] if r["pedido_id"] == "P4")
        self.assertEqual(linha["elegivel_custo"], 0)

    def test_soma_do_rateio_conserva_o_frete_valido(self):
        self.assertAlmostEqual(sum(self.custo.values()), 500.0)

    def test_ocupacao_por_peso(self):
        # 100+200+50+80 = 430 kg em 1000 kg
        self.assertAlmostEqual(self.res["kpis"]["ocupacao_pct"], 43.0)

    def test_sem_deduplicar_soma_a_copia(self):
        res = cg.compute(CFG, exemplo_quatro_linhas(), frozenset({"deduplicar_cte"}))
        self.assertAlmostEqual(res["kpis"]["custo_frete_por_entrega"], 800 / 3, places=4)


class DatasEPrazoTest(unittest.TestCase):
    def test_dias_uteis_com_e_sem_sabado(self):
        quinta = dt.date(2026, 7, 9)
        self.assertEqual(cg.somar_dias_uteis(quinta, 2, sabado=False), dt.date(2026, 7, 13))  # segunda
        self.assertEqual(cg.somar_dias_uteis(quinta, 2, sabado=True), dt.date(2026, 7, 11))   # sábado

    def test_formatos_mistos(self):
        for texto in ("2026-09-02 10:00", "02/09/2026 10:00", "02/09/26", "02.09.2026"):
            self.assertEqual(cg.parse_data_hora(texto, "%Y-%m-%d %H:%M", True).date(), dt.date(2026, 9, 2))

    def test_ingenuo_so_aceita_formato_principal(self):
        self.assertIsNone(cg.parse_data_hora("02/09/26", "%Y-%m-%d %H:%M", False))


class LimitesEConservacaoTest(unittest.TestCase):
    def test_duas_entregas_do_mesmo_pedido_exigem_outro_recorte(self):
        fontes = exemplo_quatro_linhas()
        fontes.pedidos["P1"]["qt_itens"] = 2
        fontes.entregas.append({**fontes.entregas[0], "id": 99})
        with self.assertRaisesRegex(ValueError, "uma entrega por pedido.*P1"):
            cg.compute(CFG, fontes)

    def test_custo_da_viagem_usa_o_mesmo_denominador_do_agregado(self):
        res = cg.compute(CFG, exemplo_quatro_linhas())
        viagem = res["por_viagem"][0]
        self.assertEqual(viagem["n_entregas"], 4)  # contagem operacional preservada
        self.assertEqual(viagem["n_entregas_elegiveis_custo"], 3)
        self.assertEqual(viagem["custo_frete_total"], 500.0)
        self.assertEqual(viagem["custo_por_entrega"], 166.67)

    def test_viagem_excluida_preserva_ocupacao_e_nao_tem_media_de_custo(self):
        cfg = deepcopy(CFG)
        cfg["regras_referencia"]["excluir_tipos_viagem"] = ["TRF"]
        fontes = exemplo_quatro_linhas()
        fontes.viagens["V1"]["tipo"] = "TRF"
        res = cg.compute(cfg, fontes)
        viagem = res["por_viagem"][0]
        self.assertEqual(viagem["n_entregas"], 4)
        self.assertEqual(viagem["n_entregas_elegiveis_custo"], 0)
        self.assertEqual(viagem["custo_frete_total"], 0.0)
        self.assertIsNone(viagem["custo_por_entrega"])
        self.assertIsNone(res["kpis"]["custo_frete_por_entrega"])
        self.assertIsNone(res["kpis"]["otif_pct"])
        self.assertEqual(res["kpis"]["ocupacao_pct"], 43.0)

    def test_cli_apresenta_indicadores_sem_base(self):
        cfg = deepcopy(CFG)
        cfg["regras_referencia"]["excluir_tipos_viagem"] = ["DIST"]
        with patch.object(cg, "load_cfg", return_value=cfg), \
                patch.object(cg, "load_fontes", return_value=exemplo_quatro_linhas()), \
                patch.object(cg, "write_outputs"), patch("sys.stdout", new_callable=StringIO) as output:
            self.assertEqual(cg.main(["--empresa", "mock"]), 0)
        self.assertIn("custo/entrega sem base | OTIF sem base", output.getvalue())

    def test_tercos_conservam_cem_reais_com_desempate_estavel(self):
        fontes = exemplo_quatro_linhas()
        for pid in ("P1", "P2", "P3"):
            fontes.pedidos[pid]["peso_kg"] = 1
        fontes.ctes = [{"chave": "A1", "autorizado": True, "vTPrest": 100.0,
                        "nfes": ["NFP3", "NFP2", "NFP1"]}]
        res = cg.compute(CFG, fontes)
        custos = {r["pedido_id"]: Decimal(str(r["custo_frete_rateado"])) for r in res["por_pedido"]}
        self.assertEqual(custos, {"P1": Decimal("33.34"), "P2": Decimal("33.33"),
                                  "P3": Decimal("33.33"), "P4": Decimal("0.00")})
        self.assertEqual(sum(custos.values()), Decimal("100.00"))
        self.assertEqual(res["contagens"]["frete_total_elegivel"], 100.0)
        self.assertEqual(res["por_viagem"][0]["custo_frete_total"], 100.0)
        fontes.ctes[0]["nfes"].reverse()
        self.assertEqual(res, cg.compute(CFG, fontes))

    def test_criterio_errado_e_detectado_mesmo_com_media_correta(self):
        fontes = exemplo_quatro_linhas()
        fontes.pedidos["P1"]["volume_m3"] = 2
        fontes.pedidos["P2"]["volume_m3"] = 1
        correto = cg.compute(CFG, fontes)
        cfg_errada = deepcopy(CFG)
        cfg_errada["regras_referencia"]["rateio_cte"] = "volume"
        errado = cg.compute(cfg_errada, fontes)
        self.assertEqual(correto["kpis"], errado["kpis"])
        delta, pedido = sensitivity.diferenca_rateio(correto, errado)
        self.assertEqual((delta, pedido), (1.0, "P1"))


class CancelamentoXmlTest(unittest.TestCase):
    def test_so_cancelamento_homologado_remove_o_cte(self):
        cfg = {"formato": {"csv": {"separador": ";", "decimal": ","}},
               "colunas": {nome: {} for nome in ("erp_pedidos", "tms_veiculos", "tms_viagens", "tms_entregas")}}
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp)
            for nome in ("erp/erp_pedidos.csv", "tms/tms_veiculos.csv", "tms/tms_viagens.csv", "tms/tms_entregas.csv"):
                path = pasta / nome
                path.parent.mkdir(exist_ok=True)
                path.write_text("", encoding="utf-8")
            (pasta / "cte").mkdir()
            for stat, tipo in (("135", "110111"), ("136", "110111"), ("135", "110110"), ("999", "110111")):
                with self.subTest(stat=stat, tipo=tipo):
                    (pasta / "cte/evento.xml").write_text(
                        '<procEventoCTe xmlns="http://www.portalfiscal.inf.br/cte">'
                        f'<eventoCTe><infEvento><tpEvento>{tipo}</tpEvento><chCTe>A1</chCTe></infEvento></eventoCTe>'
                        f'<retEventoCTe><infEvento><cStat>{stat}</cStat></infEvento></retEventoCTe></procEventoCTe>',
                        encoding="utf-8")
                    esperado = {"A1"} if (stat, tipo) == ("135", "110111") else set()
                    self.assertEqual(cg.load_fontes(cfg, pasta).cancelados, esperado)


class CasoExplicavelGeradoTest(unittest.TestCase):
    """Confere o caso explicável da 01 no gabarito gerado (valores definidos à mão no empresa.yaml)."""

    def test_valores(self):
        arquivo = GOLDEN / "01_demo" / "por_pedido.csv"
        if not arquivo.is_file():
            self.skipTest("gabarito da 01 ainda não calculado")
        import csv
        with arquivo.open(encoding="utf-8") as handle:
            linhas = {r["pedido_id"]: r for r in csv.DictReader(handle)}
        self.assertEqual(float(linhas["900001"]["custo_frete_rateado"]), 100.00)
        self.assertEqual(float(linhas["900002"]["custo_frete_rateado"]), 300.00)
        self.assertEqual(float(linhas["900003"]["custo_frete_rateado"]), 150.00)
        self.assertEqual(linhas["900001"]["ctes"], linhas["900002"]["ctes"])


if __name__ == "__main__":
    unittest.main()
