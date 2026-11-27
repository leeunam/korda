"""Descrição e despacho das seis ferramentas do agente sobre FerramentasAgente."""

import asyncio
import json
import unittest

from korda_execution.harness.ferramentas_agente import ESPECIFICACOES, LIMITE_SAIDA_DBT, despachar
from korda_execution.harness.politica import FERRAMENTAS

from .fakes import FerramentasFalsas

MODELO = "models/prata_ctes.sql"


def _rodar(nome, entrada, ferramentas, escritas=None):
    escritas = [] if escritas is None else escritas
    saida = asyncio.run(despachar(nome, entrada, ferramentas, escritas))
    return saida, json.loads(saida["content"][0]["text"]), escritas


class TestEspecificacoes(unittest.TestCase):
    def test_uma_especificacao_por_ferramenta(self):
        self.assertEqual(set(ESPECIFICACOES), set(FERRAMENTAS))
        for nome, (descricao, schema) in ESPECIFICACOES.items():
            with self.subTest(nome=nome):
                self.assertTrue(descricao)
                self.assertEqual(schema["type"], "object")
                self.assertIs(schema["additionalProperties"], False)


class TestDespachar(unittest.TestCase):
    def setUp(self):
        self.f = FerramentasFalsas({MODELO: "select 1"}, [MODELO])

    def test_cada_ferramenta_chega_ao_metodo_certo(self):
        casos = {
            "ler_plano": ({}, "ler_plano"),
            "inspecionar_fonte": ({"fonte": "cte"}, "inspecionar_fonte"),
            "ler_arquivo": ({"caminho": MODELO}, "ler_arquivo"),
            "rodar_dbt": ({"subcomando": "build"}, "rodar_dbt"),
            "consultar_sql": ({"sql": "select 1"}, "consultar_sql"),
        }
        for nome, (entrada, metodo) in casos.items():
            with self.subTest(nome=nome):
                saida, corpo, _ = _rodar(nome, entrada, self.f)
                self.assertTrue(corpo["ok"])
                self.assertFalse(saida["is_error"])
                self.assertEqual(self.f.chamadas[-1][0], metodo)

    def test_escrita_aceita_entra_no_registro(self):
        saida, corpo, escritas = _rodar("escrever_modelo", {"caminho": MODELO, "conteudo": "select 2"}, self.f)
        self.assertTrue(corpo["ok"])
        self.assertEqual(escritas, [MODELO])
        self.assertEqual(self.f.modelos[MODELO], "select 2")

    def test_escrita_recusada_nao_entra_no_registro(self):
        saida, corpo, escritas = _rodar("escrever_modelo", {"caminho": "tests/x.sql", "conteudo": "x"}, self.f)
        self.assertFalse(corpo["ok"])
        self.assertTrue(saida["is_error"])
        self.assertEqual(escritas, [])

    def test_saida_do_dbt_fica_com_o_final(self):
        longa = "inicio-" + "x" * 20_000 + "-Failure in test chave_fiscal_unica"
        f = FerramentasFalsas({}, [MODELO], resultados_dbt=[
            {"ok": False, "codigo": 1, "estourou_tempo": False, "duracao_s": 3.0, "stdout": longa, "stderr": "erro"}])
        _, corpo, _ = _rodar("rodar_dbt", {"subcomando": "build"}, f)
        self.assertFalse(corpo["ok"])
        self.assertLessEqual(len(corpo["saida"]), LIMITE_SAIDA_DBT)
        self.assertTrue(corpo["saida"].endswith("erro"))
        self.assertIn("chave_fiscal_unica", corpo["saida"])
        self.assertNotIn("inicio-", corpo["saida"])

    def test_saida_do_dbt_tira_o_progresso_e_guarda_erros_e_placar(self):
        saida = "\n".join([
            "12:00:00  Running with dbt=1.9.4", "12:00:00  Registered adapter: duckdb=1.9.2",
            "12:00:01  Found 5 models, 6 data tests, 5 sources, 512 macros",
            "12:00:01  1 of 3 START sql table model main.prata_ctes ..... [RUN]",
            "12:00:01  1 of 3 OK created sql table model main.prata_ctes ..... [OK in 0.04s]",
            "12:00:01  2 of 3 START test conservacao ..... [RUN]",
            "12:00:01  2 of 3 FAIL 2 conservacao ..... [FAIL 2 in 0.02s]",
            "12:00:01  3 of 3 PASS chave_fiscal_unica ..... [PASS in 0.02s]",
            "12:00:02  Failure in test conservacao (tests/conservacao.sql)", "  Got 2 results, configured to fail if != 0",
            "12:00:02  Done. PASS=2 WARN=0 ERROR=1 SKIP=0 NO-OP=0 TOTAL=3"])
        f = FerramentasFalsas({}, [MODELO], resultados_dbt=[
            {"ok": False, "codigo": 1, "estourou_tempo": False, "duracao_s": 3.0, "stdout": saida, "stderr": ""}])
        _, corpo, _ = _rodar("rodar_dbt", {"subcomando": "build"}, f)
        for fica in ("FAIL 2 conservacao", "Failure in test conservacao", "Got 2 results", "PASS=2 WARN=0 ERROR=1"):
            self.assertIn(fica, corpo["saida"])
        for sai in ("Running with dbt", "START", "OK created", "PASS chave_fiscal_unica", "Registered adapter"):
            self.assertNotIn(sai, corpo["saida"])

    def test_entrada_fora_do_schema_nao_chama_a_ferramenta(self):
        invalidas = [
            ("escrever_modelo", {"conteudo": "x"}),
            ("escrever_modelo", {"caminho": MODELO, "conteudo": 3}),
            ("rodar_dbt", {"subcomando": "build", "extra": "--profiles-dir /"}),
            ("consultar_sql", {}),
            ("ferramenta_inexistente", {}),
        ]
        for nome, entrada in invalidas:
            with self.subTest(nome=nome, entrada=entrada):
                antes = len(self.f.chamadas)
                saida, corpo, _ = _rodar(nome, entrada, self.f)
                self.assertTrue(saida["is_error"])
                self.assertFalse(corpo["ok"])
                self.assertEqual(len(self.f.chamadas), antes)


if __name__ == "__main__":
    unittest.main()
