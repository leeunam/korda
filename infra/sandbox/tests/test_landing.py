"""Landing zone completa sobre uma pasta pequena: Parquet, linhagem, rejeitados e manifesto."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import duckdb

from korda_ingestao.landing import ErroIngestao, ingerir
from test_cte import CH_A, CH_B, cte_proc, proc_evento


class TestLanding(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.entrada = self.tmp / "entrada"
        (self.entrada / "erp").mkdir(parents=True)
        (self.entrada / "cte").mkdir()
        (self.entrada / "erp" / "pedidos.csv").write_bytes(
            "cd_ped;ps_bruto;cidade\n1;363,9;São Paulo\n2;12,0\n3;;Jundiaí\n".encode("cp1252"))
        a = cte_proc(CH_A, nfes=("N1", "N2"))
        (self.entrada / "cte" / "a-cte.xml").write_bytes(a)
        (self.entrada / "cte" / "a-copia.xml").write_bytes(a)  # duplicata byte a byte
        (self.entrada / "cte" / "b-cte.xml").write_bytes(cte_proc(CH_B))
        (self.entrada / "cte" / "b-canc.xml").write_bytes(proc_evento(CH_B))
        (self.entrada / "cte" / "quebrado.xml").write_bytes(b"<cteProc")
        (self.entrada / "LEIAME.txt").write_bytes(b"nota do cliente")
        self.saida = self.tmp / "landing"
        self.manifesto = ingerir(self.entrada, self.saida)
        self.con = duckdb.connect()

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.tmp)

    def q(self, sql):
        return self.con.execute(sql.replace("@", str(self.saida) + "/")).fetchall()

    def test_csv_fiel_com_linhagem_e_rejeitado(self):
        self.assertEqual(
            self.q("select cd_ped, ps_bruto, cidade, _arquivo, _linha from '@erp/pedidos.parquet' order by _linha"),
            [("1", "363,9", "São Paulo", "erp/pedidos.csv", 2), ("3", "", "Jundiaí", "erp/pedidos.csv", 4)])
        tipos = {c: t for c, t in self.q("select column_name, column_type from (describe '@erp/pedidos.parquet')")}
        self.assertEqual(tipos["ps_bruto"], "VARCHAR")
        self.assertEqual(
            self.q("select _arquivo, _linha, motivo, conteudo_bruto from '@_rejeitados.parquet' where _linha is not null"),
            [("erp/pedidos.csv", 3, "campos_2_esperados_3", "2;12,0\n")])

    def test_cte_nada_deduplicado_nem_filtrado(self):
        self.assertEqual(self.q("select count(*), count(distinct chCTe), count(distinct _xml_sha256) from '@cte/cte.parquet'"),
                         [(3, 2, 2)])
        self.assertEqual(self.q("select count(*) from '@cte/cte_nfe.parquet' where chCTe = '%s'" % CH_A), [(4,)])
        self.assertEqual(self.q("select chCTe, tpEvento from '@cte/cte_evento.parquet'"), [(CH_B, "110111")])
        # O cteProc cancelado continua autorizado no próprio XML: o cancelamento é outro documento.
        self.assertEqual(self.q("select prot_cStat from '@cte/cte.parquet' where chCTe = '%s'" % CH_B), [("100",)])

    def test_xml_quebrado_registrado(self):
        rej = self.q("select _arquivo, motivo from '@_rejeitados.parquet' where _xml_sha256 is not null")
        self.assertEqual(len(rej), 1)
        self.assertEqual(rej[0][0], "cte/quebrado.xml")
        self.assertTrue(rej[0][1].startswith("xml_malformado"))

    def test_manifesto(self):
        m = json.loads((self.saida / "manifesto.json").read_text(encoding="utf-8"))
        self.assertIn("sintéticos", m["rotulo"])
        self.assertEqual(m["totais"], {"arquivos": 7, "csv": 1, "xml": 5, "nao_suportado": 1, "rejeitados": 2})
        csv_info = next(a for a in m["arquivos"] if a["arquivo"] == "erp/pedidos.csv")
        self.assertEqual((csv_info["codificacao"], csv_info["separador"], csv_info["cabecalho"],
                          csv_info["linhas"], csv_info["rejeitadas"]), ("cp1252", ";", True, 2, 1))
        self.assertEqual(m["tabelas"]["cte/cte"]["linhas"], 3)
        self.assertEqual(m["tabelas"]["erp/pedidos"]["colunas"][-1], {"nome": "_linha", "tipo": "BIGINT"})
        self.assertNotIn("_staging", [p.name for p in self.saida.iterdir()])

    def test_deterministico(self):
        outra = self.tmp / "landing2"
        ingerir(self.entrada, outra)
        for arq in sorted(self.saida.rglob("*")):
            if arq.is_file():
                self.assertEqual(arq.read_bytes(), (outra / arq.relative_to(self.saida)).read_bytes(), arq)

    def test_saida_nao_vazia_e_recusada(self):
        with self.assertRaises(ErroIngestao):
            ingerir(self.entrada, self.saida)

    def test_tabelas_com_mesmo_nome_sao_recusadas(self):
        (self.entrada / "cte" / "cte.csv").write_bytes(b"a;b\n1;2\n")
        with self.assertRaises(ErroIngestao):
            ingerir(self.entrada, self.tmp / "landing3")


if __name__ == "__main__":
    unittest.main()
