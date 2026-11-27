"""Aceite da landing com uma viagem, dois documentos físicos e um evento sintéticos."""

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from evaluation.worker import avaliador, landing


class TestLanding(unittest.TestCase):
    def setUp(self):
        self.base = Path(self.enterContext(TemporaryDirectory()))
        self.inventario = {}
        self.dia = "2026-09-01"
        self.dia_ant = "2026-08-31"
        self.escrever("erp/erp_clientes.csv", "cd_cli;nome\n1;Cliente sintético\n")
        self.escrever("erp/erp_pedidos.csv", "cd_ped;dt_emis;ch_nfe;ps_bruto;qt_itens\n100;2026-08-31;N1;20,0;1\n")
        self.escrever("tms/tms_veiculos.csv", "id_veic;cap_kg\nV1;100\n")
        self.escrever("tms/tms_entregas.csv", "id_ent;nr_ped;id_viag;dt_baixa;qt_entregue\n200;100;701;;1\n")
        self.escrever("tms/tms_viagens.csv", "id_viag;id_veic;dt_saida\n701;V1;2026-09-01 07:00\n")
        xml = (
            '<cteProc xmlns="http://www.portalfiscal.inf.br/cte"><CTe><infCte><ide><dhEmi>2026-09-01</dhEmi>'
            '</ide><vPrest><vTPrest>25.00</vTPrest></vPrest><infCTeNorm><infDoc><infNFe><chave>N1</chave>'
            '</infNFe></infDoc></infCTeNorm></infCte></CTe><protCTe><infProt><chCTe>CT1</chCTe>'
            '<cStat>100</cStat></infProt></protCTe></cteProc>'
        )
        self.escrever("cte/A.xml", xml)
        self.escrever("cte/A_reenvio.xml", xml)
        self.escrever("cte/cancel.xml",
                      '<procEventoCTe xmlns="http://www.portalfiscal.inf.br/cte"><eventoCTe><infEvento>'
                      '<dhEvento>2026-09-01</dhEvento><chCTe>CT2</chCTe><tpEvento>110111</tpEvento>'
                      '</infEvento></eventoCTe><retEventoCTe><infEvento><cStat>135</cStat></infEvento>'
                      '</retEventoCTe></procEventoCTe>')

    def escrever(self, nome, texto):
        arq = self.base / nome
        arq.parent.mkdir(exist_ok=True)
        arq.write_bytes(texto.encode())
        self.inventario[nome] = hashlib.sha256(arq.read_bytes()).hexdigest()

    def fixture(self, nivel):
        raw = {
            "erp/erp_clientes": {"cd_cli": "1", "nome": "Cliente sintético"},
            "erp/erp_pedidos": {"cd_ped": "100", "ch_nfe": "N1", "ps_bruto": "20,0", "qt_itens": "1", "dt_emis": self.dia_ant},
            "tms/tms_veiculos": {"id_veic": "V1", "cap_kg": "100"},
            "tms/tms_entregas": {"id_ent": "200", "nr_ped": "100", "id_viag": "701", "dt_baixa": "", "qt_entregue": "1"},
            "tms/tms_viagens": {"id_viag": "701", "id_veic": "V1", "dt_saida": self.dia + " 07:00"},
        }
        tabelas = {"_rejeitados": [], **{t: [] for t in landing.TABELAS_XML}}
        for nome, linha in raw.items():
            if nivel == 0:
                linha.update(_arquivo=nome + ".csv", _linha=2)
            else:
                linha.update(_origem=landing.TABELAS_CSV[nome][1], _carga=1)
                if nome.startswith("tms/"):
                    dia = self.dia_ant if nome.endswith("veiculos") else self.dia
                    linha["atualizado_em"] = dia + "T23:00:00-03:00"
            tabelas[nome] = [linha]
        if nivel:
            raw["erp/erp_pedidos"]["ps_bruto"] = "20.0"
            raw["tms/tms_entregas"]["dt_baixa"] = None
            raw["tms/tms_viagens"]["dt_saida"] = self.dia + "T07:00:00"
        nomes = []
        for base in ("A.xml", "A_reenvio.xml", "cancel.xml"):
            nome = (self.dia if nivel else "cte") + "/" + base
            nomes.append(nome)
            lin = {"_arquivo": nome, "_xml_sha256": self.inventario["cte/" + base]}
            if nivel:
                lin["_carga"] = 1
            if base == "cancel.xml":
                tabelas["cte/cte_evento"].append({**lin, "chCTe": "CT2", "tpEvento": "110111", "ret_cStat": "135"})
            else:
                tabelas["cte/cte"].append({**lin, "chCTe": "CT1", "prot_chCTe": "CT1", "prot_cStat": "100",
                                           "vTPrest": "25.00"})
                tabelas["cte/cte_nfe"].append({**lin, "_ordem": 1, "chCTe": "CT1", "chave": "N1"})
        meta = {"formato": "korda.landing/v0", "rejeitados": {"linhas": 0},
                "tabelas": {k: {"arquivo": k + ".parquet", "linhas": len(v)} for k,v in tabelas.items()
                            if k != "_rejeitados"}}
        estado = None
        if nivel:
            meta.update(nivel=1, plano={"company_id": "01_demo"}, cargas=[{"carga": 1}])
            estado = {"ultima_carga": 1, "cargas": [{"carga": 1}], "arquivos_cte": nomes}
        else:
            meta["arquivos"] = [{"arquivo": n, "sha256": s} for n,s in self.inventario.items()]
        return tabelas, meta, estado

    def conferir(self, nivel, fixture):
        dados, meta, estado = fixture
        janela = (self.dia, self.dia) if nivel else None
        return landing._conferir_landing(lambda t: iter(dados[t]), meta, estado, self.base,
                                         self.inventario, nivel, janela)

    def test_niveis_equivalentes_preservam_origens_diferentes(self):
        for nivel in (0, 1):
            with self.subTest(nivel=nivel):
                trilha = self.conferir(nivel, self.fixture(nivel))
                arquivo = ("2026-09-01" if nivel else "cte") + "/A.xml"
                declarado = {"pedido_id": "100", "entrega_id": "200", "viagem_id": "701", "chave_nfe": "N1",
                             "qt_itens": "1", "qt_entregue": "1", "peso_decimos_kg": "200",
                             "linhagem_cte": json.dumps([{"arquivo": arquivo, "chave_cte": "CT1",
                                 "sha256": self.inventario["cte/A.xml"], "frete_centavos": 2500,
                                 "parcela_centavos": 2500, "carga": 1 if nivel else None}])}
                for campo, nome in (("pedido", "erp/erp_pedidos"), ("entrega", "tms/tms_entregas")):
                    origem = (("", "", landing.TABELAS_CSV[nome][1], "1") if nivel else
                              (nome + ".csv", "2", "", ""))
                    declarado.update({p+"_"+campo:v for p,v in zip(("arquivo","linha","origem","carga"), origem)})
                ref = {"ctes":"CT1", "custo_frete_rateado":"25.00"}
                landing.conferir_linhagem("por_pedido.csv", declarado, ref, trilha)
                declarado["carga_pedido"] = "9"
                with self.assertRaisesRegex(ValueError, "linhagem"):
                    landing.conferir_linhagem("por_pedido.csv", declarado, ref, trilha)

    def test_leitor_parquet_real_dos_dois_niveis(self):
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError:
            self.skipTest("PyArrow ausente neste ambiente")
        for nivel in (0, 1):
            with self.subTest(nivel=nivel):
                dados, meta, estado = self.fixture(nivel)
                pasta = self.base / f"landing{nivel}"
                pasta.mkdir()
                (pasta / "manifesto.json").write_text(json.dumps(meta))
                if nivel:
                    (pasta / "_estado").mkdir()
                    (pasta / "_estado/estado.json").write_text(json.dumps(estado))
                for tabela, valores in dados.items():
                    arq = pasta / (tabela + ".parquet")
                    arq.parent.mkdir(exist_ok=True)
                    tab = pa.Table.from_pylist(valores) if valores else pa.table({"_arquivo": pa.array([], pa.string())})
                    pq.write_table(tab, arq)
                janela = (self.dia, self.dia) if nivel else None
                trilha = landing.conferir_landing(pasta, self.base, self.inventario, nivel, janela)
                self.assertEqual(len(trilha["xml"]), 3)
                arq = pasta / "cte/cte_evento.parquet"
                evento = dados["cte/cte_evento"][0]
                pq.write_table(pa.Table.from_pylist([{**evento, "_xml_sha256": "a" * 64}]), arq)
                with self.assertRaisesRegex(ValueError, "digest"):
                    landing.conferir_landing(pasta, self.base, self.inventario, nivel, janela)

    def test_documento_e_evento_divergentes_com_mesma_contagem(self):
        for tabela in ("cte/cte", "cte/cte_evento", "cte/cte_nfe"):
            with self.subTest(tabela=tabela):
                fixture = self.fixture(1)
                fixture[0][tabela][0]["_xml_sha256"] = "0" * 64
                with self.assertRaisesRegex(ValueError, "digest"):
                    self.conferir(1, fixture)
        fixture = self.fixture(0)
        fixture[0]["cte/cte_nfe"][0]["chave"] = "N2"
        with self.assertRaisesRegex(ValueError, "vínculo"):
            self.conferir(0, fixture)

    def test_estado_estoque_de_dados_e_tms_integral(self):
        fixture = self.fixture(1)
        fixture[2]["arquivos_cte"].pop()
        with self.assertRaisesRegex(ValueError, "inventário"):
            self.conferir(1, fixture)
        fixture = self.fixture(1)
        fixture[0]["tms/tms_veiculos"][0]["cap_kg"] = "105"
        with self.assertRaisesRegex(ValueError, "conteúdo"):
            self.conferir(1, fixture)
        fixture = self.fixture(0)
        fixture[1]["arquivos"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "hash"):
            self.conferir(0, fixture)

    def test_janela_parcial_bloqueia_antes_dos_arquivos_e_do_gabarito(self):
        for janela in [(self.dia_ant, self.dia), (self.dia, self.dia_ant), ("2","2")]:
            with self.subTest(janela=janela):
                r = avaliador.avaliar(self.base/"inexistente", "01_demo", fontes=self.base/"ausente",
                                      regras={}, landing=self.base/"ausente", janela_replay=janela)
                self.assertFalse(r["aprovado"])
                self.assertEqual(r["classe"], "regra")
                self.assertEqual(r["comparados"], {})
                self.assertEqual(r["janela_replay"], list(janela))

    def test_n1_sem_datas_do_controlador_bloqueia_sem_ler_gabarito(self):
        (self.base / "manifesto.json").write_text(json.dumps({"formato": "korda.landing/v0", "nivel": 1}))
        r = avaliador.avaliar(self.base/"sem-resultados", "01_demo", fontes=self.base/"sem-seed",
                              regras={}, landing=self.base)
        self.assertEqual((r["aprovado"], r["classe"], r["nivel"], r["comparados"]), (False, "regra", 1, {}))

    def test_dia_final_precisa_conferir_com_semente(self):
        dados, meta, estado = self.fixture(1)
        with self.assertRaisesRegex(ValueError, "última data"):
            landing._conferir_landing(lambda t: iter(dados[t]), meta, estado, self.base,
                                      self.inventario, 1, (self.dia_ant, self.dia_ant))


if __name__ == "__main__":
    unittest.main()
