"""Política de caminhos e de comandos das ferramentas (sem Docker)."""

import unittest

from korda_execution import caminhos
from korda_execution.caminhos import CaminhoRecusado


class TestCaminhoModelo(unittest.TestCase):
    def test_aceita_sql_em_models(self):
        self.assertEqual(
            caminhos.caminho_modelo("models/prata/prata_cte.sql"),
            "/work/projeto/models/prata/prata_cte.sql",
        )

    def test_recusa_fora_da_politica(self):
        recusados = [
            "../models/x.sql",
            "models/../tests/x.sql",
            "models/./x.sql",
            "models//x.sql",
            "models/x.sql/",
            "/work/projeto/models/x.sql",
            "tests/x.sql",
            "definicoes/x.sql",
            "dbt_project.yml",
            "models",
            "models/x.yml",
            "models/x.py",
            "models\\x.sql",
            "models/x.sql\x00.yml",
            "models/.oculto.sql",
            "models/com espaco.sql",
            "",
        ]
        for caminho in recusados:
            with self.subTest(caminho=caminho), self.assertRaises(CaminhoRecusado):
                caminhos.caminho_modelo(caminho)


class TestCaminhoLeitura(unittest.TestCase):
    def test_aceita_arquivos_do_projeto(self):
        self.assertEqual(caminhos.caminho_leitura("tests/sem_cte_cancelado.sql"),
                         "/work/projeto/tests/sem_cte_cancelado.sql")

    def test_recusa_saida_do_projeto(self):
        for caminho in ("../fontes/cte.csv", "/etc/passwd", "models/../../saida/x"):
            with self.subTest(caminho=caminho), self.assertRaises(CaminhoRecusado):
                caminhos.caminho_leitura(caminho)


class TestArgvDbt(unittest.TestCase):
    def test_lista_branca(self):
        self.assertEqual(caminhos.argv_dbt("build"), ["dbt", "--no-use-colors", "build"])
        self.assertEqual(
            caminhos.argv_dbt("test", "prata_cte+"),
            ["dbt", "--no-use-colors", "test", "--select", "prata_cte+"],
        )

    def test_recusa_subcomando_e_selecao(self):
        casos = [
            ("deps", None),
            ("run-operation", None),
            ("seed", None),
            ("build", "--full-refresh"),
            ("build", "x; rm -rf /"),
            ("build", "a b"),
            ("build", "/work/x"),
            ("debug", "x"),
        ]
        for sub, sel in casos:
            with self.subTest(sub=sub, sel=sel), self.assertRaises(CaminhoRecusado):
                caminhos.argv_dbt(sub, sel)


class TestPadraoModelo(unittest.TestCase):
    def test_aceita_caminho_exato_e_padroes_em_models(self):
        for padrao in ("models/prata_ctes.sql", "models/*", "models/*.sql", "models/prata/*"):
            with self.subTest(padrao=padrao):
                self.assertEqual(caminhos.padrao_modelo(padrao), padrao)

    def test_recusa_padrao_fora_de_models_ou_amplo_demais(self):
        for padrao in ("*", "tests/*", "models", "models/", "models/../tests/*", "models/**", "models/x.yml",
                       "models/[a-z].sql", "/work/projeto/models/*", "", None):
            with self.subTest(padrao=padrao), self.assertRaises(CaminhoRecusado):
                caminhos.padrao_modelo(padrao)

    def test_modelo_autorizado_por_padrao(self):
        self.assertTrue(caminhos.modelo_autorizado("models/ouro_kpis.sql", ["models/*"]))
        self.assertTrue(caminhos.modelo_autorizado("models/prata_ctes.sql", ["models/prata_ctes.sql"]))
        self.assertFalse(caminhos.modelo_autorizado("models/ouro_kpis.sql", ["models/prata_ctes.sql"]))
        self.assertFalse(caminhos.modelo_autorizado("tests/x.sql", ["models/*"]))
        self.assertFalse(caminhos.modelo_autorizado("models/x.sql", []))
        self.assertTrue(caminhos.modelo_autorizado("models/prata/sub/modelo.sql", ["models/prata/*.sql"]))
        self.assertFalse(caminhos.modelo_autorizado("models/ouro/modelo.sql", ["models/prata/*.sql"]))
        for invalido in ("models/../tests/a.sql", "models/schema.yml", "models//a.sql", "models/a.py"):
            with self.subTest(invalido=invalido):
                self.assertFalse(caminhos.modelo_autorizado(invalido, ["models/*"]))


if __name__ == "__main__":
    unittest.main()
