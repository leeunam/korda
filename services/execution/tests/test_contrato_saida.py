"""Contrato de saída: nomes fixos lidos dos testes protegidos e do dbt_project.yml (sem LLM)."""

import shutil
import tempfile
import unittest
from pathlib import Path

from korda_execution.contrato_saida import PROJETO, contrato_saida, texto_contrato


class TestContratoSaida(unittest.TestCase):
    def test_le_modelos_colunas_e_fontes_do_projeto(self):
        c = contrato_saida()
        self.assertEqual(set(c["modelos"]), {"prata_ctes", "prata_rateios", "ouro_kpis", "ouro_por_pedido",
                                             "ouro_por_viagem"})
        self.assertEqual(c["modelos"]["ouro_kpis"], ["custo_frete_por_entrega", "otif_pct", "ocupacao_pct"])
        self.assertLessEqual({"chave_cte", "chave_nfe", "valor_centavos"}, set(c["modelos"]["prata_ctes"]))
        self.assertLessEqual({"pedido_id", "chave_cte", "centavos", "sha256"}, set(c["modelos"]["prata_rateios"]))
        self.assertIn("otif", c["modelos"]["ouro_por_pedido"])
        self.assertIn("ocupacao", c["modelos"]["ouro_por_viagem"])
        self.assertIn("bronze_documentos", c["fontes"])
        self.assertNotIn("count", c["modelos"]["prata_ctes"])  # funções e apelidos SQL não são colunas
        # rastreabilidade_cte junta prata_ctes (apelido p) por p.sha256 e p.carga, fora da lista do select.
        self.assertLessEqual({"sha256", "carga", "arquivo"}, set(c["modelos"]["prata_ctes"]))

    def test_colunas_pelo_apelido_do_modelo(self):
        with tempfile.TemporaryDirectory() as tmp:
            projeto = Path(tmp)
            shutil.copy(PROJETO / "dbt_project.yml", projeto / "dbt_project.yml")
            (projeto / "tests").mkdir()
            (projeto / "tests/x.sql").write_text(
                "select 1 from {{ ref('prata_ctes') }} as q left join {{ ref('prata_rateios') }} on true\n"
                "where q.coluna_nova is null")
            c = contrato_saida(projeto)
        self.assertIn("coluna_nova", c["modelos"]["prata_ctes"])
        self.assertNotIn("on", c["modelos"]["prata_rateios"])

    def test_muda_quando_o_contrato_de_exportacao_muda(self):
        with tempfile.TemporaryDirectory() as tmp:
            copia = Path(tmp) / "projeto"
            shutil.copytree(PROJETO / "tests", copia / "tests")
            projeto = (PROJETO / "dbt_project.yml").read_text(encoding="utf-8")
            (copia / "dbt_project.yml").write_text(projeto.replace("otif_pct:", "otif_novo_pct:"), encoding="utf-8")
            kpis = contrato_saida(copia)["modelos"]["ouro_kpis"]
        self.assertIn("otif_novo_pct", kpis)
        self.assertNotIn("otif_pct", kpis)

    def test_projeto_sem_contrato_de_exportacao_e_erro(self):
        with tempfile.TemporaryDirectory() as tmp:
            copia = Path(tmp) / "projeto"
            shutil.copytree(PROJETO / "tests", copia / "tests")
            (copia / "dbt_project.yml").write_text("name: x\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "contrato_exportacao"):
                contrato_saida(copia)

    def test_texto_lista_cada_modelo(self):
        texto = texto_contrato()
        self.assertIn("Nomes fixos", texto)
        for modelo in ("prata_ctes", "prata_rateios", "ouro_kpis", "ouro_por_pedido", "ouro_por_viagem"):
            self.assertIn(f"- {modelo}:", texto)


if __name__ == "__main__":
    unittest.main()
