"""Configuração do harness: qual corretor roda e o portão da chave do LLM (sem LLM)."""

import unittest

from korda_execution.harness.config import ConfigHarness, ErroConfiguracao

AGENTE_LIBERADO = {"KORDA_CORRETOR": "agente", "KORDA_PERMITIR_LLM_REAL": "1"}


class TestConfigHarness(unittest.TestCase):
    def test_padrao_e_roteirizado_sem_chave(self):
        cfg = ConfigHarness.de_ambiente({})
        self.assertEqual(cfg.corretor, "roteirizado")
        self.assertEqual(cfg.modelo, "claude-opus-5-5")
        self.assertEqual(cfg.orcamento_execucao_usd, 3.0)
        self.assertEqual(cfg.max_turnos_tentativa, 12)
        self.assertEqual(cfg.taxa_usd_brl, 6.0)
        self.assertFalse(cfg.permitir_llm_real)
        self.assertIsNone(cfg.chave_api)

    def test_agente_sem_chave_falha_com_mensagem(self):
        for chave in (None, "", "   "):
            env = dict(AGENTE_LIBERADO)
            if chave is not None:
                env["ANTHROPIC_API_KEY"] = chave
            with self.subTest(chave=chave), self.assertRaises(ErroConfiguracao) as ctx:
                ConfigHarness.de_ambiente(env)
            self.assertIn("ANTHROPIC_API_KEY", str(ctx.exception))
            self.assertIn(".env.example", str(ctx.exception))

    def test_agente_sem_permissao_explicita_falha(self):
        env = {"KORDA_CORRETOR": "agente", "ANTHROPIC_API_KEY": "sk-teste"}
        with self.assertRaises(ErroConfiguracao) as ctx:
            ConfigHarness.de_ambiente(env)
        self.assertIn("KORDA_PERMITIR_LLM_REAL", str(ctx.exception))

    def test_agente_liberado(self):
        cfg = ConfigHarness.de_ambiente({**AGENTE_LIBERADO, "ANTHROPIC_API_KEY": " sk-teste "})
        self.assertEqual(cfg.corretor, "agente")
        self.assertTrue(cfg.permitir_llm_real)
        self.assertEqual(cfg.chave_api, "sk-teste")

    def test_chave_nao_aparece_no_repr(self):
        cfg = ConfigHarness.de_ambiente({**AGENTE_LIBERADO, "ANTHROPIC_API_KEY": "sk-teste"})
        self.assertNotIn("sk-teste", repr(cfg))
        self.assertNotIn("sk-teste", str(cfg))

    def test_valores_invalidos(self):
        invalidos = [
            {"KORDA_ORCAMENTO_EXECUCAO_USD": "0"},
            {"KORDA_ORCAMENTO_EXECUCAO_USD": "-1"},
            {"KORDA_ORCAMENTO_EXECUCAO_USD": "abc"},
            {"KORDA_ORCAMENTO_EXECUCAO_USD": "nan"},
            {"KORDA_MAX_TURNOS_TENTATIVA": "0"},
            {"KORDA_MAX_TURNOS_TENTATIVA": "2.5"},
            {"KORDA_TAXA_USD_BRL": "0"},
            {"KORDA_CORRETOR": "devin"},
            {"KORDA_MODELO": "  "},
        ]
        for env in invalidos:
            with self.subTest(env=env), self.assertRaises(ErroConfiguracao):
                ConfigHarness.de_ambiente(env)


if __name__ == "__main__":
    unittest.main()
