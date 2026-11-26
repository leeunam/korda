"""O que o agente vê: projeção do plano, falha e perfis (sem LLM)."""

import os
import unittest
from unittest import mock

from korda_execution.harness.contexto import CAMPOS_PLANO, LIMITE_PERFIS, SISTEMA, montar_prompt, projetar_plano

PLANO = {
    "schema_version": "0.1.0",
    "plan_version": "a" * 64,
    "project_id": "demo-01",
    "destination": "revisao-logistica",
    "evidence": [{"quote": "CT-e cancelado não conta"}],
    "sources": [{"id": "cte"}],
    "editable_models": ["models/prata_ctes.sql"],
    "limits": {"max_repair_attempts_per_step": 3},
    "rules": {"deduplicar_cte": {"value": True, "evidence": ["e1"]}, "rateio_cte": {"value": "peso"}},
    "metrics": {
        "custo_frete_por_entrega": {"formula": "segredo da fórmula", "acceptance": ["chave fiscal única"],
                                    "grain": "entrega"},
        "otif_pct": {"acceptance": ["no prazo e completo"]},
    },
}
FALHA = {"ok": False, "codigo": "implementacao", "erro": "Failure in test chave_fiscal_unica (77 linhas)"}


class TestProjecao(unittest.TestCase):
    def test_mantem_so_os_cinco_campos(self):
        projecao = projetar_plano(PLANO)
        self.assertEqual(set(projecao), set(CAMPOS_PLANO))
        self.assertEqual(projecao["rules"], {"deduplicar_cte": True, "rateio_cte": "peso"})
        self.assertEqual(projecao["metrics"]["custo_frete_por_entrega"], {"acceptance": ["chave fiscal única"]})

    def test_aceita_regras_ja_projetadas_pelo_worker(self):
        projecao = projetar_plano({**PLANO, "rules": {"deduplicar_cte": True}})
        self.assertEqual(projecao["rules"], {"deduplicar_cte": True})

    def test_campo_obrigatorio_ausente(self):
        incompleto = {k: v for k, v in PLANO.items() if k != "editable_models"}
        with self.assertRaises(ValueError):
            projetar_plano(incompleto)


class TestPrompt(unittest.TestCase):
    def _prompt(self, perfis=None):
        return montar_prompt(FALHA, 2, 3, projetar_plano(PLANO), perfis or {"cte": {"linhas": 3494}})

    def test_conteudo_essencial(self):
        texto = self._prompt()
        self.assertIn("models/prata_ctes.sql", texto)
        self.assertIn("chave_fiscal_unica", texto)
        self.assertIn("tentativa 2 de 3", texto)
        self.assertIn("chave fiscal única", texto)

    def test_nao_vaza_o_que_nao_deve(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-segredo-teste"}):
            texto = SISTEMA + self._prompt()
        for proibido in ("evaluation", "golden", "sk-segredo-teste", "segredo da fórmula", "revisao-logistica",
                         "CT-e cancelado não conta"):
            self.assertNotIn(proibido, texto)

    def test_deterministico(self):
        self.assertEqual(self._prompt(), self._prompt())

    def test_perfis_grandes_sao_cortados(self):
        texto = self._prompt({"cte": {"amostra": "x" * (LIMITE_PERFIS * 2)}})
        self.assertLess(len(texto), LIMITE_PERFIS + 4_000)
        self.assertIn("cortado", texto)

    def test_sistema_define_limites(self):
        for trecho in ("editable_models", "testes", "fontes", "rodar_dbt"):
            self.assertIn(trecho, SISTEMA)


if __name__ == "__main__":
    unittest.main()
