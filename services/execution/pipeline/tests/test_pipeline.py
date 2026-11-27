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
from unittest.mock import Mock, patch
from pathlib import Path
from xml.etree import ElementTree

PROJETO = Path(__file__).resolve().parents[1] / "projeto"
REPO = PROJETO.parents[3]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(PROJETO))
sys.path.insert(0, str(REPO / "infra/sandbox"))
sys.path.insert(0, str(REPO / "services/execution/referencia"))

from exportar import contrato_exportacao, exportar
from ingerir import Landing, REGRAS_SUPORTADAS, documentos, ingerir, validar_regras

try:
    from jinja2 import Environment, StrictUndefined
except ImportError:
    Environment = None

try:
    from korda_ingestao.landing import ingerir as landing_n0
except ModuleNotFoundError as exc:
    if exc.name != "duckdb":
        raise
    landing_n0 = None


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


def renderizar(arquivo, adaptador="sqlite"):
    env = Environment(undefined=StrictUndefined)
    meio_par = env.from_string((PROJETO / "macros/meio_par.sql").read_text()).module.meio_par
    return env.from_string(arquivo.read_text()).render(
        ref=lambda nome: nome, source=lambda fonte, nome: nome, meio_par=meio_par,
        target={"type": adaptador}, var={"contrato_exportacao": contrato_exportacao()}.__getitem__,
        config=lambda **kwargs: "")


def construir_modelos(conn):
    for nome in ("prata_ctes", "prata_rateios", "ouro_por_pedido", "ouro_por_viagem", "ouro_kpis"):
        sql = renderizar(PROJETO / "models" / (nome + ".sql"))
        conn.execute(f"create table {nome} as " + sql)


class TestRegras(unittest.TestCase):
    def test_usa_apenas_regras_implementadas(self):
        for regras in ({}, {**REGRAS_SUPORTADAS, "deduplicar_cte": 1},
                       {**REGRAS_SUPORTADAS, "rateio_cte": "valor"}):
            with self.subTest(regras=regras), self.assertRaises(ValueError):
                validar_regras(regras)


@unittest.skipUnless(Environment is not None, "a renderização dos testes dbt requer Jinja2")
class TestContratoExportacao(unittest.TestCase):
    def setUp(self):
        self.contrato = contrato_exportacao()
        self.teste = renderizar(PROJETO / "tests/contrato_exportacao.sql")
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        valores = {"inteiro": 1, "numero": 1.5, "texto": "x", "flag": 1, "data_iso": "2026-09-01"}
        for tabela, campos in self.contrato.items():
            self.conn.execute(f"create table {tabela} ({', '.join(campos)})")
            params = ', '.join('?' for _ in campos)
            self.conn.execute(f"insert into {tabela} values ({params})", [valores[t] for t in campos.values()])

    def test_aceita_relacoes_compativeis(self):
        self.assertEqual(self.conn.execute(self.teste).fetchall(), [])

    def test_coluna_ausente_em_cada_relacao_falha_no_build(self):
        for tabela, campos in self.contrato.items():
            with self.subTest(tabela=tabela):
                ultimo = list(campos)[-1]
                self.conn.execute(f"alter table {tabela} rename column {ultimo} to omitida")
                with self.assertRaisesRegex(sqlite3.OperationalError, ultimo):
                    self.conn.execute(self.teste)
                self.conn.execute(f"alter table {tabela} rename column omitida to {ultimo}")

    def test_tipo_incompativel_identifica_coluna_e_relacao(self):
        self.conn.execute("update ouro_por_pedido set qt_itens = 'quatro'")
        self.conn.execute("update prata_rateios set valor_centavos = 1.25")
        falhas = self.conn.execute(self.teste).fetchall()
        self.assertCountEqual(falhas, [("ouro_por_pedido", "qt_itens", "inteiro", "TEXT"),
                                      ("prata_rateios", "valor_centavos", "inteiro", "REAL")])

    @unittest.skipUnless(landing_n0, "verificação estática nativa requer DuckDB")
    def test_duckdb_distingue_coluna_vazia_de_tipo_incorreto(self):
        import duckdb

        tipos = {"inteiro": "HUGEINT", "numero": "DECIMAL(18,4)", "texto": "VARCHAR",
                 "flag": "BOOLEAN", "data_iso": "DATE"}
        sql = renderizar(PROJETO / "tests/contrato_exportacao.sql", "duckdb")
        with duckdb.connect(config={"threads": 1}) as con:
            for tabela, campos in self.contrato.items():
                ddl = ", ".join(f"{nome} {tipos[tipo]}" for nome, tipo in campos.items())
                con.execute(f"create table {tabela} ({ddl})")
            self.assertEqual(con.execute(sql).fetchall(), [])
            con.execute("alter table ouro_kpis alter otif_pct type varchar")
            self.assertEqual(con.execute(sql).fetchall(), [("ouro_kpis", "otif_pct", "numero", "VARCHAR")])
            con.execute("alter table ouro_kpis drop column otif_pct")
            with self.assertRaises(duckdb.BinderException):
                con.execute(sql)


@unittest.skipUnless(Environment is not None, "a renderização dos testes dbt requer Jinja2")
class TestReferenciasCTe(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.dados = renderizar(PROJETO / "tests/integridade_fontes.sql")
        self.modelo = renderizar(PROJETO / "tests/rastreabilidade_cte.sql")
        self.conn.executescript("""
            create table bronze_pedidos (arquivo, origem, pedido_id, chave_nfe, qt_itens);
            create table bronze_entregas (arquivo, origem, entrega_id, pedido_id, viagem_id);
            create table bronze_viagens (arquivo, origem, viagem_id, veiculo_id, tipo_viagem);
            create table bronze_veiculos (arquivo, origem, veiculo_id);
            create table bronze_documentos (arquivo, sha256, carga, especie, chave_cte, cstat,
                                           tipo_evento, chave_nfe, valor_centavos);
            insert into bronze_pedidos values ('erp.csv', null, 'p1', 'N1', 1), ('erp.csv', null, 'p2', 'N2', 2);
            insert into bronze_entregas values ('entregas.csv', null, 'e1', 'p1', 'v1'),
                                              ('entregas.csv', null, 'e2', 'p2', 'v1');
            insert into bronze_viagens values ('viagens.csv', null, 'v1', 'x1', 'DIST');
            insert into bronze_veiculos values ('veiculos.csv', null, 'x1');
            insert into bronze_documentos values ('a.xml', 'hash-a', null, 'cte', 'A', '100', null, 'N1', 1350);
        """)

    def test_nfe_errada_no_modelo_e_corrigivel_com_fontes_integras(self):
        # A checagem da fonte roda mesmo antes de existir qualquer modelo.
        self.assertEqual(self.conn.execute(self.dados).fetchall(), [])
        modelo = renderizar(PROJETO / "models/prata_ctes.sql")
        self.conn.execute("create table prata_ctes as " + modelo)
        self.assertEqual(self.conn.execute(self.modelo).fetchall(), [])
        for nf in ("INVENTADA", "N2"):  # N2 existe no ERP, porém pertence a outro vínculo.
            with self.subTest(nf=nf):
                self.conn.execute("update prata_ctes set chave_nfe = ?", [nf])
                self.assertEqual(self.conn.execute(self.dados).fetchall(), [])
                self.assertEqual(self.conn.execute(self.modelo).fetchall(), [("A", nf, "a.xml")])
        self.conn.execute("drop table prata_ctes")
        self.conn.execute("create table prata_ctes as " + modelo)
        self.assertEqual(self.conn.execute(self.modelo).fetchall(), [])

    def test_documento_sem_pedido_na_origem_so_e_excluido_com_cancelamento_homologado(self):
        self.conn.execute("update bronze_documentos set chave_nfe = 'SEM-PEDIDO'")
        falha = [("a.xml", "SEM-PEDIDO")]
        self.assertEqual(self.conn.execute(self.dados).fetchall(), falha)
        self.conn.execute("insert into bronze_documentos values "
                          "('ev.xml', 'hash-ev', null, 'evento', 'A', '136', '110111', null, null)")
        self.assertEqual(self.conn.execute(self.dados).fetchall(), falha)
        self.conn.execute("update bronze_documentos set cstat = '135' where especie = 'evento'")
        self.assertEqual(self.conn.execute(self.dados).fetchall(), [])


class TestProjecaoLanding(unittest.TestCase):
    def test_une_nfes_a_copia_fisica_e_preserva_carga(self):
        chave = "A"
        original = ("2026-09-01/a.xml", "a" * 64, 1)
        reenvio = ("2026-09-02/a.xml", "a" * 64, 2)
        registro = (chave, "CTeA", chave, "100", "13.50")
        tabelas = {"cte/cte": [(original, registro), (reenvio, registro)],
                   "cte/cte_nfe": [(original, (chave, "1")), (reenvio, (chave, "1"))], "cte/cte_evento": []}
        landing = Mock(spec=Landing)
        landing.ler.side_effect = tabelas.__getitem__
        rows = list(documentos(landing))
        self.assertEqual([(r[0], r[2], r[-2:]) for r in rows],
                         [(original[0], 1, ("1", 1350)), (reenvio[0], 2, ("1", 1350))])
        # A chave fiscal sozinha não vincula o documento a um filho de outro arquivo/carga.
        tabelas["cte/cte_nfe"].pop()
        with self.assertRaisesRegex(ValueError, "sem NF-e correspondente"):
            list(documentos(landing))

    def test_carga_api_tem_origem_e_preserva_ausencia_de_linha_fisica(self):
        landing = Mock(spec=Landing, nivel=1)
        landing.ler.return_value = [(("tms:/entregas", 7), ("e1",))]
        self.assertEqual(list(Landing.registros(landing, "tms/tms_entregas")),
                         [((None, None, "tms:/entregas", 7), ("e1",))])
        landing.ler.return_value = [(("tms:/entregas", 0), ("e1",))]
        with self.assertRaisesRegex(ValueError, "linhagem"):
            list(Landing.registros(landing, "tms/tms_entregas"))


@unittest.skipUnless(landing_n0, "a landing Parquet requer o DuckDB fixado da sandbox")
class TestPipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pasta = Path(self.tmp.name)
        self.bruto = self.pasta / "bruto"
        fontes(self.bruto)
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)

    def materializar(self):
        destino = self.pasta / "landing"
        landing_n0(self.bruto, destino)
        return destino

    def test_erro_em_xml_reverte_ingestao_inteira(self):
        escrever(self.bruto, "cte/quebrado.xml", "<cte")
        with self.assertRaisesRegex(ValueError, "rejeições"):
            ingerir(self.conn, self.materializar(), REGRAS_SUPORTADAS)
        self.assertEqual(self.conn.execute("select count(*) from sqlite_master").fetchone(), (0,))

    def test_reentrega_exige_novo_plano(self):
        with (self.bruto / "tms/tms_entregas.csv").open("a") as fp:
            fp.write("e4;1;v1;2026-11-21 12:00;1\n")
        with self.assertRaises(sqlite3.IntegrityError):
            ingerir(self.conn, self.materializar(), REGRAS_SUPORTADAS)

    @unittest.skipUnless(Environment is not None and sqlite3.sqlite_version_info >= (3, 44),
                         "ensaio complementar requer Jinja2 e SQLite 3.44+")
    def test_landing_n1_reune_cargas_sem_inventar_arquivo_ou_linha_de_api(self):
        from ingestao_n1 import __main__ as n1

        # ERP e TMS já entregam registros estruturados nos respectivos protocolos.
        # A fixture substitui os transportes e executa o escritor de landing N1 de referência.
        plano = json.loads((REPO / "packages/contracts/ingestion_plan/v0.1.0/examples/01_demo.json").read_text())
        data = "2026-11-20"
        arqs = self.pasta / "entrega" / data
        arqs.mkdir(parents=True)
        for xml in (self.bruto / "cte").glob("a*.xml"):
            (arqs / xml.name).write_bytes(xml.read_bytes())
        erp = {"erp_pedidos": (["cd_ped", "ch_nfe", "dt_prev_ent", "qt_itens", "ps_bruto"],
                               [["1", "N1", data, "2", "10.0"], ["2", "N2", data, "2", "30.0"],
                                ["3", "N3", data, "2", "10.0"]])}
        veiculos = [{"id_veic": "c1", "cap_kg": "20"}]
        viagens = [{"id_viag": v, "id_veic": "c1", "tp_viag": "DIST"} for v in ("v1", "v2", "v3")]
        entregas = [{"id_ent": "e" + p, "nr_ped": p, "id_viag": v, "dt_baixa": baixa, "qt_entregue": n}
                    for p, v, baixa, n in (("1", "v1", "20/11/26", "2"), ("2", "v1", "20/11/2026 10:00", "1"),
                                           ("3", "v2", None, "2"))]
        landing = self.pasta / "landing-n1"
        inicial = {"erp_pedidos": (erp["erp_pedidos"][0], erp["erp_pedidos"][1][:2])}
        tms = {"tms_veiculos": (veiculos, data), "tms_viagens": (viagens[:1], data),
               "tms_entregas": (entregas[:2], data)}
        with patch.object(n1, "ler_erp", return_value=inicial), patch.object(n1, "ler_tms", return_value=tms):
            self.assertEqual(n1.executar(plano, landing, arqs.parent)["carga"], 1)
        seguinte = "2026-11-21"
        proxima = arqs.parent / seguinte
        proxima.mkdir()
        for xml in (self.bruto / "cte").glob("b*.xml"):
            (proxima / xml.name).write_bytes(xml.read_bytes())
        tms = {"tms_veiculos": ([], data), "tms_viagens": (viagens[1:], seguinte),
               "tms_entregas": (entregas[2:], seguinte)}
        with patch.object(n1, "ler_erp", return_value=erp), patch.object(n1, "ler_tms", return_value=tms):
            self.assertEqual(n1.executar(plano, landing, arqs.parent)["carga"], 2)
        ingerir(self.conn, landing, REGRAS_SUPORTADAS)
        construir_modelos(self.conn)
        destino = self.pasta / "saidas"
        exportar(self.conn, destino)
        with (destino / "por_pedido.csv").open() as fp:
            pedido = next(csv.DictReader(fp))
        self.assertEqual((pedido["origem_pedido"], pedido["carga_pedido"]), ("erp:erp_pedidos", "2"))
        self.assertEqual((pedido["origem_entrega"], pedido["carga_entrega"]), ("tms:/entregas", "1"))
        self.assertEqual((pedido["arquivo_pedido"], pedido["linha_entrega"]), ("", ""))
        cte = json.loads(pedido["linhagem_cte"])[0]
        self.assertEqual(cte["carga"], 1)
        self.assertTrue(cte["arquivo"].startswith(data + "/"))
        self.assertEqual(cte["sha256"], hashlib.sha256((arqs.parent / cte["arquivo"]).read_bytes()).hexdigest())
        self.assertEqual(json.loads((destino / "kpis.json").read_text())["kpis"], {
            "custo_frete_por_entrega": 0.03, "otif_pct": 33.3333, "ocupacao_pct": 83.3333})

    @unittest.skipUnless(Environment is not None and sqlite3.sqlite_version_info >= (3, 44),
                         "ensaio SQL complementar requer Jinja2 e SQLite 3.44+")
    def test_caso_calculado_a_mao(self):
        ingerir(self.conn, self.materializar(), REGRAS_SUPORTADAS)
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
        self.assertEqual(origem["sha256"], hashlib.sha256((self.bruto / origem["arquivo"]).read_bytes()).hexdigest())
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
        escrever(self.bruto, "cte/a-copia.xml", cte("A", ["N1", "N2"], "900.00"))
        ingerir(self.conn, self.materializar(), REGRAS_SUPORTADAS)
        sql = renderizar(PROJETO / "tests/documentos_conflitantes.sql")
        self.assertEqual(self.conn.execute(sql).fetchall(), [("A",)])


@unittest.skipUnless(Environment is not None and sqlite3.sqlite_version_info >= (3, 44),
                     "ensaio SQL complementar requer Jinja2 e SQLite 3.44+")
@unittest.skipUnless(landing_n0, "a landing Parquet requer o DuckDB fixado da sandbox")
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
                # O gerador inclui uma pasta privada. A montagem do worker expõe só ERP, TMS e CT-e.
                (fontes / "_gerador").rename(raiz / "metadados-do-gerador")
                landing = raiz / "landing"
                landing_n0(fontes, landing)
                ingerir(conn, landing, regras)
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
