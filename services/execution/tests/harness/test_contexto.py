"""O que o agente vê: projeção do plano, falha e perfis (sem LLM)."""

import os
import unittest
from unittest import mock

from korda_execution.harness.contexto import (CAMPOS_PLANO, LIMITE_DOCUMENTO, LIMITE_PERFIS, SISTEMA, SISTEMA_CONSTRUCAO,
                                             montar_prompt, montar_prompt_construcao, projetar_plano)

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
        "custo_frete_por_entrega": {"formula": "frete alocado / entregas elegíveis", "acceptance": ["chave fiscal única"],
                                    "grain": "entrega", "state": "planejada", "blocking_gaps": []},
        "otif_pct": {"acceptance": ["no prazo e completo"]},
    },
    "tasks": [{"id": "prata", "depends_on": ["bronze"], "output": "CT-e deduplicados", "verify": "chave única"},
              {"id": "bronze", "depends_on": [], "output": "fontes brutas", "verify": "conciliar arquivos"}],
}
FALHA = {"ok": False, "codigo": "implementacao", "erro": "Failure in test chave_fiscal_unica (77 linhas)"}


class TestProjecao(unittest.TestCase):
    def test_mantem_so_os_campos_de_construcao(self):
        projecao = projetar_plano(PLANO)
        self.assertEqual(set(projecao), set(CAMPOS_PLANO))
        self.assertEqual(projecao["rules"], {"deduplicar_cte": True, "rateio_cte": "peso"})
        self.assertEqual(projecao["metrics"]["custo_frete_por_entrega"],
                         {"formula": "frete alocado / entregas elegíveis", "acceptance": ["chave fiscal única"],
                          "grain": "entrega"})

    def test_tarefas_em_ordem_topologica(self):
        self.assertEqual([t["id"] for t in projetar_plano(PLANO)["tasks"]], ["bronze", "prata"])

    def test_tarefas_com_ciclo_sao_recusadas(self):
        ciclo = [{"id": "a", "depends_on": ["b"], "output": "x", "verify": "y"},
                 {"id": "b", "depends_on": ["a"], "output": "x", "verify": "y"}]
        with self.assertRaises(ValueError):
            projetar_plano({**PLANO, "tasks": ciclo})

    def test_dependencia_inexistente_e_recusada(self):
        with self.assertRaises(ValueError):
            projetar_plano({**PLANO, "tasks": [{"id": "a", "depends_on": ["z"], "output": "x", "verify": "y"}]})

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
        for proibido in ("evaluation", "golden", "sk-segredo-teste", "revisao-logistica", "CT-e cancelado não conta",
                         "planejada"):
            self.assertNotIn(proibido, texto)

    def test_deterministico(self):
        self.assertEqual(self._prompt(), self._prompt())

    def test_perfis_grandes_sao_cortados(self):
        texto = self._prompt({"cte": {"amostra": "x" * (LIMITE_PERFIS * 2)}})
        self.assertLess(len(texto), LIMITE_PERFIS + 4_000)
        self.assertIn("cortado", texto)

    def test_sistema_define_limites(self):
        for sistema in (SISTEMA, SISTEMA_CONSTRUCAO):
            for trecho in ("editable_models", "testes", "fontes", "rodar_dbt"):
                self.assertIn(trecho, sistema)


class TestPromptConstrucao(unittest.TestCase):
    def test_traz_tarefas_metricas_e_documento_base(self):
        texto = montar_prompt_construcao(projetar_plano(PLANO), {"cte": {"linhas": 3}}, "# Especificação\nRatear por peso.")
        self.assertIn("frete alocado / entregas elegíveis", texto)
        self.assertLess(texto.index('"bronze"'), texto.index('"prata"'))
        self.assertIn("Ratear por peso.", texto)
        self.assertNotIn("golden", SISTEMA_CONSTRUCAO + texto)

    def test_sem_documento_base(self):
        texto = montar_prompt_construcao(projetar_plano(PLANO), {}, None)
        self.assertIn("sem documento-base", texto)

    def test_documento_grande_e_cortado(self):
        texto = montar_prompt_construcao(projetar_plano(PLANO), {}, "x" * (LIMITE_DOCUMENTO * 2))
        self.assertLess(len(texto), LIMITE_DOCUMENTO + 6_000)


class TestPromptConstrucaoEnxuto(unittest.TestCase):
    def test_traz_o_contrato_e_nao_repete_as_tarefas(self):
        publico = projetar_plano(PLANO)
        texto = montar_prompt_construcao(publico, {}, "doc")
        self.assertIn("Contrato de saída", texto)
        for nome in ("prata_ctes", "prata_rateios", "ouro_kpis", "ouro_por_pedido", "ouro_por_viagem",
                     "custo_frete_rateado", "bronze_documentos"):
            self.assertIn(nome, texto)
        self.assertEqual(texto.count('"depends_on"'), len(publico["tasks"]))

    def test_regras_falam_de_cte_selecao_e_historico_resumido(self):
        for trecho in ("CTEs", "'<modelo>+'", "resumidos", "information_schema"):
            self.assertIn(trecho, SISTEMA_CONSTRUCAO)


class TestContratoDeSaida(unittest.TestCase):
    def test_construcao_aponta_o_contrato_de_saida(self):
        from korda_execution.harness.contexto import SISTEMA, SISTEMA_CONSTRUCAO

        for sistema in (SISTEMA, SISTEMA_CONSTRUCAO):
            self.assertIn("exportar.py", sistema)
            self.assertIn("ouro_kpis", sistema)


if __name__ == "__main__":
    unittest.main()
