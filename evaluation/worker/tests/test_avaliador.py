"""Ensaios do laudo sobre duas entregas e uma viagem fictícias, calculados à mão."""

import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from evaluation.worker import avaliador


PEDIDOS = (
    "pedido_id,viagem_id,tipo_viagem,elegivel_custo,custo_frete_rateado,ctes,data_prevista,"
    "data_realizada,elegivel_otif,no_prazo,completo,otif\n"
    "100,701,DIST,1,25.00,cteA,2026-08-01,2026-08-01,1,1,1,1\n"
    "101,701,DIST,1,75.00,cteA,2026-08-01,2026-08-01,1,1,0,0\n"
)
VIAGENS = (
    "viagem_id,veiculo_id,tipo_viagem,n_entregas,n_entregas_elegiveis_custo,carga,custo_frete_total,"
    "capacidade,unidade,ocupacao,acima_capacidade,custo_por_entrega\n"
    "701,V1,DIST,2,2,400,100.00,500,kg,0.8,0,50.00\n"
)
KPIS = {"custo_frete_por_entrega": 50, "otif_pct": 50, "ocupacao_pct": 80}
REGRAS = {"rateio_cte": "peso", "sem_data_realizada": "falha", "ocupacao_unidade": "kg",
          "prazo_conta_sabado": True, "excluir_tipos_viagem": []}


class TestAvaliador(unittest.TestCase):
    def setUp(self):
        tmp = self.enterContext(TemporaryDirectory())
        pasta = Path(tmp)
        self.ref = pasta / "referencia" / "01_demo"
        self.ref.mkdir(parents=True)
        self.enterContext(patch.object(avaliador, "GOLDEN", self.ref.parent))
        self.saida = pasta / "saida"
        self.saida.mkdir()
        self.fontes = pasta / "fontes"
        for subpasta in ("erp", "tms", "cte"):
            (self.fontes / subpasta).mkdir(parents=True)
        csv = b"pedido_id,peso\n100,100\n101,300\n"
        (self.fontes / "erp" / "pedidos.csv").write_bytes(csv)
        (self.ref / "fontes.sha256").write_text(f"{hashlib.sha256(csv).hexdigest()}  erp/pedidos.csv\n")
        for d in (self.ref, self.saida):
            (d / "por_pedido.csv").write_text(PEDIDOS)
            (d / "por_viagem.csv").write_text(VIAGENS)
        (self.ref / "kpis.json").write_text(json.dumps({"empresa_id": "01_demo", "kpis": KPIS,
                                                        "regras_referencia": REGRAS}))
        self.gravar_kpis(KPIS)

    def gravar_kpis(self, kpis):
        (self.saida / "kpis.json").write_text(json.dumps({"kpis": kpis}))

    def avaliar(self, **kwargs):
        return avaliador.avaliar(self.saida, "01_demo", **kwargs)

    def test_resultados_e_fontes_conferidos(self):
        linhas = PEDIDOS.splitlines()
        (self.saida / "por_pedido.csv").write_text("\n".join([linhas[0], linhas[2], linhas[1]]) + "\n")
        r = self.avaliar(fontes=self.fontes, regras=REGRAS)
        self.assertTrue(r["aprovado"], r)
        self.assertTrue(r["fontes_conferidas"])
        self.assertTrue(r["regras_conferidas"])
        self.assertEqual(r["comparados"], {"kpis": 3, "por_pedido.csv": 2, "por_viagem.csv": 1})

    def test_rateio_invertido_com_agregado_correto(self):
        (self.saida / "por_pedido.csv").write_text(PEDIDOS.replace("25.00", "30.00").replace("75.00", "70.00"))
        r = self.avaliar()
        self.assertFalse(r["aprovado"])
        self.assertEqual((r["classe"], r["divergencias"]), ("implementacao", 2))
        self.assertEqual(r["exemplos"][0], {"local": "por_pedido.csv/100", "campo": "custo_frete_rateado",
                                           "esperado": "25.00", "encontrado": "30.00"})

    def test_um_centavo_divergente_e_suficiente(self):
        (self.saida / "por_pedido.csv").write_text(PEDIDOS.replace("25.00", "25.01"))
        self.assertEqual(self.avaliar()["divergencias"], 1)

    def test_ocupacao_aceita_dois_vizinhos_so_em_empate_decimal_comprovado(self):
        ref = self.ref / "por_viagem.csv"
        saida = self.saida / "por_viagem.csv"
        empate = VIAGENS.replace("400,100.00,500,kg,0.8", "3437,100.00,4000,kg,0.8593")
        ref.write_text(empate)
        saida.write_text(empate.replace("0.8593", "0.8592"))
        self.assertTrue(self.avaliar()["aprovado"])
        saida.write_text(empate.replace("0.8593", "0.8591"))
        self.assertFalse(self.avaliar()["aprovado"])
        sem_empate = empate.replace("3437,", "3437.1,")
        ref.write_text(sem_empate)
        saida.write_text(sem_empate.replace("0.8593", "0.8592"))
        self.assertFalse(self.avaliar()["aprovado"])

    def test_ausencia_extra_e_duplicata(self):
        caminho = self.saida / "por_pedido.csv"
        caminho.write_text(PEDIDOS.replace("101,701", "104,701"))
        r = self.avaliar()
        self.assertEqual(r["divergencias"], 2)
        self.assertEqual([x["esperado"] for x in r["exemplos"]], ["101", None])
        caminho.write_text(PEDIDOS.replace("101,701", "100,701"))
        self.assertIn("repetido", self.avaliar()["erro"])

    def test_regras_incompativeis_e_cenario_sem_referencia(self):
        r = self.avaliar(regras={**REGRAS, "rateio_cte": "volume"})
        self.assertEqual(r["classe"], "regra")
        self.assertFalse(r["aprovado"])
        self.assertEqual(avaliador.avaliar(self.saida, "cenario_customizado")["classe"], "regra")

    def test_fontes_divergentes(self):
        original = self.fontes / "erp" / "pedidos.csv"
        conteudo = original.read_bytes()
        original.write_bytes(conteudo + b"\n")
        self.assertIn("conteúdo", self.avaliar(fontes=self.fontes)["erro"])
        original.unlink()
        self.assertIn("ausente", self.avaliar(fontes=self.fontes)["erro"])
        original.write_bytes(conteudo)
        (self.fontes / "cte" / "documento-extra.xml").write_text("<doc/>")
        self.assertEqual(self.avaliar(fontes=self.fontes)["classe"], "dados")

    def test_nao_aceita_vinculo_em_artefato_ou_pasta(self):
        arq = self.saida / "kpis.json"
        arq.unlink()
        arq.symlink_to(self.ref / "kpis.json")
        r = self.avaliar()
        self.assertFalse(r["aprovado"])
        self.assertEqual(r["classe"], "implementacao")
        arq.unlink()
        os.link(self.ref / "kpis.json", arq)
        self.assertFalse(self.avaliar()["aprovado"])
        arq.unlink()
        self.gravar_kpis(KPIS)
        alias = self.saida.parent / "alias"
        alias.symlink_to(self.saida, target_is_directory=True)
        self.assertFalse(avaliador.avaliar(alias, "01_demo")["aprovado"])

    def test_arquivo_truncado_sem_kpi_e_numero_invalido(self):
        kpi = self.saida / "kpis.json"
        for valor in ("null", "true", "1e100000000", '"NaN"', "NaN"):
            with self.subTest(valor=valor):
                kpi.write_text('{"kpis":{"custo_frete_por_entrega":' + valor +
                               ',"ocupacao_pct":80,"otif_pct":50}}')
                self.assertFalse(self.avaliar()["aprovado"])
        for texto in ('{"kpis":{}', '{"kpis":{}}', '{"kpis":{},"kpis":{}}'):
            kpi.write_text(texto)
            self.assertFalse(self.avaliar()["aprovado"])
        self.gravar_kpis(KPIS)
        (self.saida / "por_viagem.csv").write_text(VIAGENS.rstrip().removesuffix(",50.00"))
        self.assertIn("largura", self.avaliar()["erro"])

    def test_diferenca_entre_nulo_e_zero(self):
        ref = self.ref / "kpis.json"
        origem = json.loads(ref.read_text())
        origem["kpis"]["otif_pct"] = None
        ref.write_text(json.dumps(origem))
        self.gravar_kpis({**KPIS, "otif_pct": 0})
        self.assertEqual(self.avaliar()["divergencias"], 1)
        self.gravar_kpis({**KPIS, "otif_pct": None})
        self.assertTrue(self.avaliar()["aprovado"])


if __name__ == "__main__":
    unittest.main()
