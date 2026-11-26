"""Política das ferramentas do agente e hook PreToolUse (sem SDK, sem LLM)."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from korda_execution.eventos import EmissorEventos
from korda_execution.harness.politica import FERRAMENTAS, PREFIXO, avaliar_chamada, hook_pre_tool_use

EDITAVEIS = frozenset({"models/prata_ctes.sql"})


class TestAvaliarChamada(unittest.TestCase):
    def test_permite_ferramentas_korda(self):
        self.assertEqual(len(FERRAMENTAS), 6)
        permitidas = [
            ("escrever_modelo", {"caminho": "models/prata_ctes.sql", "conteudo": "select 1"}),
            ("rodar_dbt", {"subcomando": "build"}),
            ("ler_arquivo", {"caminho": "tests/chave_fiscal_unica.sql"}),
            ("ler_plano", {}),
        ]
        for nome, entrada in permitidas:
            with self.subTest(nome=nome):
                self.assertTrue(avaliar_chamada(PREFIXO + nome, entrada, EDITAVEIS).permitir)

    def test_nega_ferramentas_fora_do_korda(self):
        for nome in ("Bash", "Read", "Write", "Edit", "WebFetch", "Agent", "mcp__outro__escrever_modelo",
                     "mcp__korda__apagar", "mcp__korda__", "", "mcp__korda__escrever_modelo_x"):
            with self.subTest(nome=nome):
                decisao = avaliar_chamada(nome, {}, EDITAVEIS)
                self.assertFalse(decisao.permitir)
                self.assertTrue(decisao.motivo)

    def test_nega_escrita_fora_dos_modelos_autorizados(self):
        for caminho in ("tests/chave_fiscal_unica.sql", "definicoes/fontes.yml", "models/ouro_kpis.sql",
                        "models/../tests/x.sql", "models/prata_ctes.sql/", "MODELS/prata_ctes.sql",
                        "models/prata_ctes.yml", "/work/projeto/models/prata_ctes.sql",
                        "models//prata_ctes.sql", "./models/prata_ctes.sql", "", None, 42):
            with self.subTest(caminho=caminho):
                entrada = {"caminho": caminho, "conteudo": "select 1"}
                self.assertFalse(avaliar_chamada(PREFIXO + "escrever_modelo", entrada, EDITAVEIS).permitir)

    def test_nega_escrita_sem_caminho(self):
        self.assertFalse(avaliar_chamada(PREFIXO + "escrever_modelo", {"conteudo": "x"}, EDITAVEIS).permitir)


class TestHook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.emissor = EmissorEventos(Path(self.tmp.name) / "eventos.jsonl", "run-teste")

    def tearDown(self):
        self.tmp.cleanup()

    def _chamar(self, nome, entrada):
        hook = hook_pre_tool_use(EDITAVEIS, self.emissor, obter_tentativa=lambda: 2)
        return asyncio.run(hook({"hook_event_name": "PreToolUse", "tool_name": nome, "tool_input": entrada},
                                "toolu_1", None))

    def test_hook_permite_sem_decisao(self):
        self.assertEqual(self._chamar(PREFIXO + "escrever_modelo", {"caminho": "models/prata_ctes.sql"}), {})
        self.assertEqual(self.emissor.ler(), [])

    def test_hook_nega_e_registra_evento(self):
        saida = self._chamar(PREFIXO + "escrever_modelo", {"caminho": "tests/chave_fiscal_unica.sql"})
        especifico = saida["hookSpecificOutput"]
        self.assertEqual(especifico["hookEventName"], "PreToolUse")
        self.assertEqual(especifico["permissionDecision"], "deny")
        self.assertTrue(especifico["permissionDecisionReason"])
        eventos = self.emissor.ler()
        self.assertEqual(len(eventos), 1)
        self.assertEqual(eventos[0]["type"], "tool_refused")
        self.assertEqual(eventos[0]["step"], "construcao")
        self.assertEqual(eventos[0]["attempt"], 2)
        self.assertEqual(eventos[0]["dados"]["origem"], "hook")
        self.assertEqual(eventos[0]["dados"]["ferramenta"], "escrever_modelo")

    def test_hook_nega_embutida(self):
        saida = self._chamar("Bash", {"command": "cat evaluation/golden/01_demo/kpis.json"})
        self.assertEqual(saida["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertNotIn("kpis.json", self.emissor.ler()[0]["message"])


if __name__ == "__main__":
    unittest.main()
