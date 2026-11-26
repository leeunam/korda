"""Fontes pequenas independentes e verificações do SQL do projeto da demonstração."""

import csv
from collections import Counter
from contextlib import closing
from decimal import Decimal
import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree

PROJETO = Path(__file__).resolve().parents[1] / "projeto"
REPO = PROJETO.parents[3]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(PROJETO))

from exportar import exportar
from ingerir import REGRAS_SUPORTADAS, ingerir, validar_regras

try:
    from jinja2 import Environment, StrictUndefined
except ImportError:
    Environment = None


def escrever(raiz, nome, conteudo):
    path = raiz / nome
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(conteudo, encoding="utf-8")


def cte(chave, nfes, valor):
    notas = "".join(f"<infNFe><chave>{n}</chave></infNFe>" for n in nfes)
    return (f'<cteProc xmlns="http://www.portalfiscal.inf.br/cte"><CTe><infCte Id="CTe{chave}">'
            f'<vPrest><vTPrest>{valor}</vTPrest></vPrest><infCTeNorm><infDoc>{notas}</infDoc>'
            f'</infCTeNorm></infCte></CTe><protCTe><infProt><cStat>100</cStat><chCTe>{chave}</chCTe>'
            f'</infProt></protCTe></cteProc>')


def evento(chave, status):
    ids = f"<chCTe>{chave}</chCTe><tpEvento>110111</tpEvento>"
    return (f'<procEventoCTe xmlns="http://www.portalfiscal.inf.br/cte"><eventoCTe><infEvento>{ids}'
            f'</infEvento></eventoCTe><retEventoCTe><infEvento>{ids}<cStat>{status}</cStat>'
            f'</infEvento></retEventoCTe></procEventoCTe>')


def fontes(raiz):
    escrever(raiz, "erp/erp_pedidos.csv",
             "cd_ped;ch_nfe;dt_prev_ent;qt_itens;ps_bruto\n"
             "1;N1;2026-11-20;2;10,0\n2;N2;2026-11-20;2;30,0\n3;N3;2026-11-20;2;10,0\n")
    escrever(raiz, "tms/tms_entregas.csv",
             "id_ent;nr_ped;id_viag;dt_baixa;qt_entregue\n"
             "e1;1;v1;20/11/26;2\ne2;2;v1;20/11/2026 10:00;1\ne3;3;v2;;2\n")
    escrever(raiz, "tms/tms_viagens.csv",
             "id_viag;id_veic;tp_viag\nv1;c1;DIST\nv2;c1;DIST\nv3;c1;DIST\n")
    escrever(raiz, "tms/tms_veiculos.csv", "id_veic;cap_kg\nc1;20\n")
    compartilhado = cte("A", ["N1", "N2"], "0.06")
    escrever(raiz, "cte/a.xml", compartilhado)
    escrever(raiz, "cte/a-copia.xml", compartilhado)
    escrever(raiz, "cte/b.xml", cte("B", ["N3"], "100"))
    escrever(raiz, "cte/b-cancelado.xml", evento("B", "135"))
    escrever(raiz, "cte/a-evento-sem-vinculo.xml", evento("A", "136"))


def renderizar(arquivo):
    env = Environment(undefined=StrictUndefined)
    meio_par = env.from_string((PROJETO / "macros/meio_par.sql").read_text()).module.meio_par
    return env.from_string(arquivo.read_text()).render(
        ref=lambda nome: nome, source=lambda fonte, nome: nome, meio_par=meio_par)


def construir_modelos(conn):
    for nome in ("prata_ctes", "prata_rateios", "ouro_por_pedido", "ouro_por_viagem", "ouro_kpis"):
        sql = renderizar(PROJETO / "models" / (nome + ".sql"))
        conn.execute(f"create table {nome} as " + sql)


class TestPipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pasta = Path(self.tmp.name)
        fontes(self.pasta)
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)

    def test_usa_apenas_regras_implementadas(self):
        for regras in ({}, {**REGRAS_SUPORTADAS, "deduplicar_cte": 1},
                       {**REGRAS_SUPORTADAS, "rateio_cte": "valor"}):
            with self.subTest(regras=regras), self.assertRaises(ValueError):
                validar_regras(regras)

    def test_erro_em_xml_reverte_ingestao_inteira(self):
        escrever(self.pasta, "cte/quebrado.xml", "<cte")
        with self.assertRaisesRegex(ValueError, "quebrado.xml"):
            ingerir(self.conn, self.pasta, REGRAS_SUPORTADAS)
        self.assertEqual(self.conn.execute("select count(*) from sqlite_master").fetchone(), (0,))

    def test_reentrega_exige_novo_plano(self):
        with (self.pasta / "tms/tms_entregas.csv").open("a") as fp:
            fp.write("e4;1;v1;2026-11-21 12:00;1\n")
        with self.assertRaises(sqlite3.IntegrityError):
            ingerir(self.conn, self.pasta, REGRAS_SUPORTADAS)

    @unittest.skipUnless(Environment is not None and sqlite3.sqlite_version_info >= (3, 44),
                         "ensaio SQL complementar requer Jinja2 e SQLite 3.44+")
    def test_caso_calculado_a_mao(self):
        ingerir(self.conn, self.pasta, REGRAS_SUPORTADAS)
        construir_modelos(self.conn)
        for arquivo in (PROJETO / "tests").glob("*.sql"):
            with self.subTest(arquivo=arquivo.name):
                self.assertEqual(self.conn.execute(renderizar(arquivo)).fetchall(), [])
        destino = self.pasta / "privado"
        exportar(self.conn, destino)
        with (destino / "por_pedido.csv").open() as fp:
            pedidos = list(csv.DictReader(fp))
        self.assertEqual([float(p["custo_frete_rateado"]) for p in pedidos], [0.02, 0.04, 0.0])
        origem = json.loads(pedidos[0]["linhagem_cte"])[0]
        self.assertEqual(origem["parcela_centavos"], 2)
        self.assertEqual(origem["frete_centavos"], 6)
        self.assertEqual(origem["sha256"], hashlib.sha256((self.pasta / origem["arquivo"]).read_bytes()).hexdigest())
        self.assertEqual(pedidos[1]["arquivo_pedido"], "erp/erp_pedidos.csv")
        self.assertEqual(pedidos[1]["linha_pedido"], "3")
        self.assertEqual(json.loads(pedidos[2]["linhagem_cte"]), [])
        self.assertEqual([p["otif"] for p in pedidos], ["1", "0", "0"])
        self.assertEqual([p["elegivel_custo"] for p in pedidos], ["1", "1", "0"])
        with (destino / "por_viagem.csv").open() as fp:
            viagens = list(csv.DictReader(fp))
        self.assertEqual(viagens[0]["arquivo_veiculo"], "tms/tms_veiculos.csv")
        self.assertEqual(viagens[0]["linha_veiculo"], "2")
        self.assertEqual(viagens[0]["acima_capacidade"], "1")
        self.assertEqual(viagens[2]["n_entregas"], "0")
        self.assertEqual(viagens[2]["custo_por_entrega"], "")
        self.assertEqual(json.loads((destino / "kpis.json").read_text())["kpis"], {
            "custo_frete_por_entrega": 0.03, "otif_pct": 33.3333, "ocupacao_pct": 83.3333})
        origem = self.conn.execute("select arquivo_pedido, linha_pedido, arquivo_entrega, linha_entrega "
                                   "from ouro_por_pedido where pedido_id = '2'").fetchone()
        self.assertEqual(origem, ("erp/erp_pedidos.csv", 3, "tms/tms_entregas.csv", 3))
        self.assertEqual(self.conn.execute("select count(distinct arquivo) from bronze_documentos "
                                           "where chave_cte = 'A'").fetchone(), (3,))

    @unittest.skipUnless(Environment is not None and sqlite3.sqlite_version_info >= (3, 44),
                         "ensaio SQL complementar requer Jinja2 e SQLite 3.44+")
    def test_documentos_mesma_chave_com_valores_divergentes_falham(self):
        escrever(self.pasta, "cte/a-copia.xml", cte("A", ["N1", "N2"], "900.00"))
        ingerir(self.conn, self.pasta, REGRAS_SUPORTADAS)
        sql = renderizar(PROJETO / "tests/documentos_conflitantes.sql")
        self.assertEqual(self.conn.execute(sql).fetchall(), [("A",)])


@unittest.skipUnless(Environment is not None and sqlite3.sqlite_version_info >= (3, 44),
                     "ensaio SQL complementar requer Jinja2 e SQLite 3.44+")
class TestLoteCompleto(unittest.TestCase):
    def test_01_demo_regenerado_confere_com_avaliador_e_fontes(self):
        from data.synthetic.generator.generate import generate
        from evaluation.worker.avaliador import avaliar

        contexto = REPO / "packages/contracts/context/v0.1.0/examples/02_rateio_confirmado.json"
        regras = {nome: dado["value"] for nome, dado in json.loads(contexto.read_text())["rules"].items()}
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            gerado = generate("01_demo", output_root=raiz / "fontes")
            fontes = raiz / "fontes/01_demo"
            saida = raiz / "resultados"
            with closing(sqlite3.connect(":memory:")) as conn:
                ingerir(conn, fontes, regras)
                construir_modelos(conn)
                for arquivo in sorted((PROJETO / "tests").glob("*.sql")):
                    with self.subTest(teste=arquivo.name):
                        self.assertEqual(conn.execute(renderizar(arquivo)).fetchall(), [])
                exportar(conn, saida)
            laudo = avaliar(saida, "01_demo", fontes=fontes, regras=regras)
            self.assertTrue(laudo["aprovado"], laudo)
            self.assertEqual(laudo["divergencias"], 0)
            self.assertEqual(laudo["comparados"], {"kpis": 3, "por_pedido.csv": gerado["tabelas"]["erp_pedidos"],
                                                   "por_viagem.csv": gerado["viagens"]["total"]})
            self.conferir_linhagem(fontes, saida)

    def conferir_linhagem(self, fontes, saida):
        tabelas = {}
        for caminho in ("erp/erp_pedidos.csv", "tms/tms_entregas.csv", "tms/tms_viagens.csv", "tms/tms_veiculos.csv"):
            with (fontes / caminho).open(newline="", encoding="utf-8") as fp:
                csv_fonte = csv.DictReader(fp, delimiter=";")
                tabelas[caminho] = {csv_fonte.line_num: linha for linha in csv_fonte}

        def linha_referenciada(registro, nome):
            return tabelas[registro["arquivo_" + nome]][int(registro["linha_" + nome])]

        somas = Counter()
        documentos = {}
        with (saida / "por_pedido.csv").open(newline="", encoding="utf-8") as fp:
            for pedido in csv.DictReader(fp):
                erp = linha_referenciada(pedido, "pedido")
                baixa = linha_referenciada(pedido, "entrega")
                self.assertEqual((erp["cd_ped"], erp["ch_nfe"]), (pedido["pedido_id"], pedido["chave_nfe"]))
                self.assertEqual((baixa["nr_ped"], baixa["id_ent"]), (pedido["pedido_id"], pedido["entrega_id"]))
                parcelas = json.loads(pedido["linhagem_cte"])
                self.assertEqual(sum(p["parcela_centavos"] for p in parcelas),
                                 Decimal(pedido["custo_frete_rateado"]) * 100)
                for parcela in parcelas:
                    chave = parcela["chave_cte"]
                    if chave not in documentos:
                        bruto = (fontes / parcela["arquivo"]).read_bytes()
                        xml = ElementTree.fromstring(bruto)
                        self.assertEqual(xml.findtext(".//{*}infProt/{*}chCTe"), chave)
                        documentos[chave] = (hashlib.sha256(bruto).hexdigest(),
                                             Decimal(xml.findtext(".//{*}vPrest/{*}vTPrest")) * 100,
                                             {n.text for n in xml.findall(".//{*}infNFe/{*}chave")})
                    digest, total, notas = documentos[chave]
                    self.assertEqual(parcela["sha256"], digest)
                    self.assertEqual(parcela["frete_centavos"], total)
                    self.assertIn(pedido["chave_nfe"], notas)
                    somas[chave] += parcela["parcela_centavos"]
        self.assertEqual(somas, {chave: dados[1] for chave, dados in documentos.items()})
        with (saida / "por_viagem.csv").open(newline="", encoding="utf-8") as fp:
            for viagem in csv.DictReader(fp):
                rota = linha_referenciada(viagem, "viagem")
                cadastro = linha_referenciada(viagem, "veiculo")
                self.assertEqual((rota["id_viag"], rota["id_veic"]), (viagem["viagem_id"], viagem["veiculo_id"]))
                self.assertEqual(cadastro["id_veic"], viagem["veiculo_id"])


if __name__ == "__main__":
    unittest.main()
