"""Configuração do harness: qual executor roda e o portão da chave do LLM (sem LLM)."""

import unittest

from korda_execution.harness.config import ConfigHarness, ErroConfiguracao

CHAT_LIBERADO = {"KORDA_EXECUTOR": "chat", "KORDA_PERMITIR_LLM_REAL": "1"}
SDK_LIBERADO = {"KORDA_EXECUTOR": "agente_sdk", "KORDA_PERMITIR_LLM_REAL": "1"}


class TestPadroes(unittest.TestCase):
    def test_padrao_e_roteirizado_sem_chave(self):
        cfg = ConfigHarness.de_ambiente({})
        self.assertEqual(cfg.executor, "roteirizado")
        self.assertEqual(cfg.orcamento_execucao_usd, 8.0)
        self.assertEqual(cfg.max_turnos_construcao, 40)
        self.assertEqual(cfg.max_turnos_tentativa, 12)
        self.assertEqual(cfg.taxa_usd_brl, 6.0)
        self.assertEqual((cfg.preco_entrada_usd_mtok, cfg.preco_saida_usd_mtok), (4.0, 20.0))
        self.assertFalse(cfg.permitir_llm_real)
        self.assertIsNone(cfg.chave_api)
        self.assertFalse(cfg.usa_llm)

    def test_chat_usa_o_gateway_da_feita_por_padrao(self):
        cfg = ConfigHarness.de_ambiente({**CHAT_LIBERADO, "KORDA_LLM_CHAVE": "fk-teste"})
        self.assertEqual(cfg.llm_url, "https://api.feita.ai/gateway/v1")
        self.assertEqual(cfg.modelo, "anthropic/claude-opus-5.5")
        self.assertEqual(cfg.chave_api, "fk-teste")
        self.assertTrue(cfg.usa_llm)

    def test_agente_sdk_usa_a_chave_da_anthropic(self):
        cfg = ConfigHarness.de_ambiente({**SDK_LIBERADO, "ANTHROPIC_API_KEY": " sk-teste "})
        self.assertEqual(cfg.modelo, "claude-opus-5-5")
        self.assertEqual(cfg.chave_api, "sk-teste")


class TestPortao(unittest.TestCase):
    def test_chat_sem_chave_falha_com_mensagem(self):
        for chave in (None, "", "   "):
            env = dict(CHAT_LIBERADO)
            if chave is not None:
                env["KORDA_LLM_CHAVE"] = chave
            with self.subTest(chave=chave), self.assertRaises(ErroConfiguracao) as ctx:
                ConfigHarness.de_ambiente(env)
            self.assertIn("KORDA_LLM_CHAVE", str(ctx.exception))
            self.assertIn(".env.example", str(ctx.exception))

    def test_agente_sdk_sem_chave_falha_com_mensagem(self):
        with self.assertRaises(ErroConfiguracao) as ctx:
            ConfigHarness.de_ambiente(SDK_LIBERADO)
        self.assertIn("ANTHROPIC_API_KEY", str(ctx.exception))

    def test_llm_sem_permissao_explicita_falha(self):
        for executor, chave in (("chat", "KORDA_LLM_CHAVE"), ("agente_sdk", "ANTHROPIC_API_KEY")):
            with self.subTest(executor=executor), self.assertRaises(ErroConfiguracao) as ctx:
                ConfigHarness.de_ambiente({"KORDA_EXECUTOR": executor, chave: "segredo"})
            self.assertIn("KORDA_PERMITIR_LLM_REAL", str(ctx.exception))

    def test_chave_nao_aparece_no_repr(self):
        cfg = ConfigHarness.de_ambiente({**CHAT_LIBERADO, "KORDA_LLM_CHAVE": "fk-segredo"})
        self.assertNotIn("fk-segredo", repr(cfg))

    def test_url_precisa_ser_https(self):
        with self.assertRaises(ErroConfiguracao):
            ConfigHarness.de_ambiente({**CHAT_LIBERADO, "KORDA_LLM_CHAVE": "x", "KORDA_LLM_URL": "http://exemplo.com/v1"})

    def test_valores_invalidos(self):
        invalidos = [
            {"KORDA_ORCAMENTO_EXECUCAO_USD": "0"}, {"KORDA_ORCAMENTO_EXECUCAO_USD": "abc"},
            {"KORDA_ORCAMENTO_EXECUCAO_USD": "nan"}, {"KORDA_MAX_TURNOS_TENTATIVA": "0"},
            {"KORDA_MAX_TURNOS_CONSTRUCAO": "2.5"}, {"KORDA_MAX_TURNOS_TENTATIVA": "²"},
            {"KORDA_TAXA_USD_BRL": "0"}, {"KORDA_PRECO_SAIDA_USD_MTOK": "-1"},
            {"KORDA_EXECUTOR": "devin"}, {"KORDA_MODELO": "  "}, {"KORDA_CORRETOR": "agente"},
        ]
        for env in invalidos:
            with self.subTest(env=env), self.assertRaises(ErroConfiguracao):
                ConfigHarness.de_ambiente(env)


if __name__ == "__main__":
    unittest.main()
