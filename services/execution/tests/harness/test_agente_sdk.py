"""CorretorAgente com sessão falsa: nenhum teste aqui abre o CLI nem chama o LLM."""

import asyncio
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

from korda_execution.eventos import EmissorEventos
from korda_execution.harness.agente_sdk import (EMBUTIDAS, ContextoSessao, CorretorAgente, ErroSegurancaHarness,
                                                SaidaSessao, construir_opcoes, verificar_ferramentas_sessao)
from korda_execution.harness.config import ConfigHarness
from korda_execution.harness.contexto import projetar_plano
from korda_execution.harness.ferramentas_agente import despachar
from korda_execution.harness.medicao import Medidor
from korda_execution.harness.politica import PREFIXO

from .fakes import FerramentasFalsas

MODELO = "models/prata_ctes.sql"
FALHA = {"ok": False, "codigo": "implementacao", "erro": "Failure in test chave_fiscal_unica"}
PLANO = {"plan_version": "a" * 64, "editable_models": [MODELO], "limits": {"max_repair_attempts_per_step": 3},
         "rules": {"deduplicar_cte": True}, "metrics": {"custo_frete_por_entrega": {"acceptance": ["única"]}},
         "tasks": [{"id": "prata", "depends_on": [], "output": "ctes", "verify": "única"}]}
SDK_INSTALADO = importlib.util.find_spec("claude_agent_sdk") is not None
FERRAMENTAS_OK = [PREFIXO + n for n in ("ler_plano", "escrever_modelo", "rodar_dbt")]


def _cfg(**extra):
    env = {"KORDA_EXECUTOR": "agente_sdk", "KORDA_PERMITIR_LLM_REAL": "1", "ANTHROPIC_API_KEY": "sk-teste",
           "KORDA_ORCAMENTO_EXECUCAO_USD": "3.00", **extra}
    return ConfigHarness.de_ambiente(env)


class SessaoFalsa:
    """Simula sessões do SDK: cada item diz custo, subtype e se escreve o modelo."""

    def __init__(self, sessoes):
        self.sessoes = list(sessoes)
        self.chamadas: list[ContextoSessao] = []

    def __call__(self, prompt: str, ctx: ContextoSessao) -> SaidaSessao:
        self.chamadas.append(ctx)
        s = self.sessoes.pop(0)
        if isinstance(s, Exception):
            raise s
        if s.get("escreve"):
            asyncio.run(despachar("escrever_modelo", {"caminho": MODELO, "conteudo": "select distinct 1"},
                                  ctx.ferramentas, ctx.escritas))
        return SaidaSessao(subtype=s.get("subtype", "success"), num_turns=s.get("turnos", 4),
                           total_cost_usd=s.get("custo"),
                           usage={"input_tokens": 1000, "output_tokens": 200, "cache_read_input_tokens": 10},
                           ferramentas_sessao=FERRAMENTAS_OK)


class TestCorretorAgente(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.emissor = EmissorEventos(Path(self.tmp.name) / "eventos.jsonl", "run-teste")
        self.medidor = Medidor("run-teste", "agente_sdk", "claude-opus-5-5")
        self.f = FerramentasFalsas({MODELO: "select 1"}, [MODELO])

    def tearDown(self):
        self.tmp.cleanup()

    def _corretor(self, sessao, cfg=None):
        return CorretorAgente(cfg or _cfg(), self.f, projetar_plano(PLANO), {"cte": {}}, 3, self.emissor,
                              self.medidor, rodar_sessao=sessao)

    def test_corrige_e_informa_custo_em_centavos_de_real(self):
        sessao = SessaoFalsa([{"escreve": True, "custo": 0.40}])
        resultado = self._corretor(sessao)(FALHA, 1)
        self.assertEqual(resultado, {"ok": True, "custo_centavos": 240})
        self.assertEqual(self.medidor.resumo()["tentativas"], 1)
        fim = [e for e in self.emissor.ler() if e["type"] == "agent_finished"]
        self.assertEqual(len(fim), 1)
        self.assertEqual(fim[0]["dados"]["ferramentas_sessao"], FERRAMENTAS_OK)
        self.assertEqual(fim[0]["dados"]["subtype"], "success")

    def test_teto_por_tentativa_tem_folga(self):
        sessao = SessaoFalsa([{"escreve": True, "custo": 0.1}])
        self._corretor(sessao)(FALHA, 1)
        self.assertAlmostEqual(sessao.chamadas[0].max_budget_usd, 3.0 / 3 * 0.9)

    def test_sessao_com_ferramenta_embutida_aborta(self):
        sessao = SessaoFalsa([ErroSegurancaHarness("sessão expôs Bash")])
        with self.assertRaises(ErroSegurancaHarness):
            self._corretor(sessao)(FALHA, 1)
        self.assertEqual(self.f.escritas(), [])

    def test_orcamento_esgotado_nao_abre_sessao(self):
        sessao = SessaoFalsa([{"escreve": True, "custo": 1.40}, {"escreve": True, "custo": 1.60},
                              {"escreve": True, "custo": 0.1}])
        corretor = self._corretor(sessao)
        corretor(FALHA, 1)
        corretor(FALHA, 2)
        resultado = corretor(FALHA, 3)
        self.assertEqual(resultado, {"ok": False, "erro": "orçamento de LLM esgotado", "custo_centavos": 0})
        self.assertEqual(len(sessao.chamadas), 2)

    def test_teto_da_tentativa_respeita_o_restante(self):
        sessao = SessaoFalsa([{"escreve": True, "custo": 2.80}, {"escreve": True, "custo": 0.1}])
        corretor = self._corretor(sessao)
        corretor(FALHA, 1)
        corretor(FALHA, 2)
        self.assertAlmostEqual(sessao.chamadas[1].max_budget_usd, 0.2 * 0.9)

    def test_sem_escrita_devolve_ok_false(self):
        sessao = SessaoFalsa([{"subtype": "error_max_turns", "custo": 0.30}])
        resultado = self._corretor(sessao)(FALHA, 1)
        self.assertFalse(resultado["ok"])
        self.assertIn("error_max_turns", resultado["erro"])
        self.assertEqual(resultado["custo_centavos"], 180)

    def test_erro_de_execucao_mesmo_com_escrita_devolve_ok_false(self):
        sessao = SessaoFalsa([{"subtype": "error_during_execution", "escreve": True, "custo": 0.1}])
        self.assertFalse(self._corretor(sessao)(FALHA, 1)["ok"])

    def test_custo_desconhecido(self):
        sessao = SessaoFalsa([{"escreve": True, "custo": None}, {"escreve": True, "custo": None}])
        corretor = self._corretor(sessao)
        self.assertIsNone(corretor(FALHA, 1)["custo_centavos"])
        self.assertFalse(self.medidor.resumo()["custo_completo"])
        # Custo desconhecido consome o teto da tentativa, por precaução.
        self.assertAlmostEqual(corretor.gasto_usd, 0.9)

    def test_exige_config_de_agente(self):
        cfg = ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "falso"})
        with self.assertRaises(ValueError):
            self._corretor(SessaoFalsa([]), cfg=cfg)


class TestVerificacaoDaSessao(unittest.TestCase):
    def test_aceita_so_ferramentas_korda(self):
        verificar_ferramentas_sessao(FERRAMENTAS_OK)

    def test_recusa_embutida(self):
        for extra in ("Bash", "Read", "ListMcpResourcesTool", "mcp__outro__x"):
            with self.subTest(extra=extra), self.assertRaises(ErroSegurancaHarness):
                verificar_ferramentas_sessao(FERRAMENTAS_OK + [extra])


@unittest.skipUnless(SDK_INSTALADO, "claude-agent-sdk não instalado (requirements-harness.txt)")
class TestOpcoes(unittest.TestCase):
    def test_opcoes_desligam_embutidas(self):
        from claude_agent_sdk import create_sdk_mcp_server

        servidor = create_sdk_mcp_server(name="korda", tools=[])
        with tempfile.TemporaryDirectory() as vazio:
            opcoes = construir_opcoes(_cfg(), servidor, lambda *a: {}, Path(vazio), 0.9)
        self.assertEqual(opcoes.tools, [])
        for nome in ("Bash", "Read", "Write", "Edit", "WebFetch", "Agent"):
            self.assertIn(nome, opcoes.disallowed_tools)
        self.assertEqual(set(opcoes.disallowed_tools), set(EMBUTIDAS))
        self.assertTrue(opcoes.allowed_tools)
        self.assertTrue(all(t.startswith(PREFIXO) for t in opcoes.allowed_tools))
        self.assertEqual(opcoes.setting_sources, [])
        self.assertEqual(opcoes.permission_mode, "dontAsk")
        self.assertEqual(opcoes.max_turns, 12)
        self.assertAlmostEqual(opcoes.max_budget_usd, 0.9)
        self.assertEqual(opcoes.model, "claude-opus-5-5")
        self.assertEqual(list(opcoes.mcp_servers), ["korda"])
        self.assertEqual(len(opcoes.hooks["PreToolUse"]), 1)
        self.assertIsNone(opcoes.hooks["PreToolUse"][0].matcher)
        self.assertEqual(opcoes.env, {"ANTHROPIC_API_KEY": "sk-teste"})
        self.assertNotIn("sk-teste", str(opcoes.system_prompt))


@unittest.skipUnless(SDK_INSTALADO, "claude-agent-sdk não instalado (requirements-harness.txt)")
class TestFerramentasDoSdk(unittest.TestCase):
    def test_seis_ferramentas_chamam_o_mesmo_despacho(self):
        from korda_execution.harness.agente_sdk import ferramentas_sdk

        f = FerramentasFalsas({MODELO: "select 1"}, [MODELO])
        ctx = ContextoSessao(_cfg(), f, lambda *a: {}, 0.9)
        ferramentas = {t.name: t for t in ferramentas_sdk(ctx)}
        self.assertEqual(set(ferramentas), {"ler_plano", "inspecionar_fonte", "ler_arquivo", "escrever_modelo",
                                            "rodar_dbt", "consultar_sql"})
        saida = asyncio.run(ferramentas["escrever_modelo"].handler({"caminho": MODELO, "conteudo": "select 2"}))
        self.assertFalse(saida["is_error"])
        self.assertEqual(ctx.escritas, [MODELO])
        saida = asyncio.run(ferramentas["escrever_modelo"].handler({"caminho": "tests/x.sql", "conteudo": "x"}))
        self.assertTrue(saida["is_error"])
        self.assertEqual(ctx.escritas, [MODELO])


@unittest.skipUnless(os.environ.get("KORDA_PERMITIR_LLM_REAL") == "1", "LLM real exige autorização (Tarefa 12)")
class TestAgenteReal(unittest.TestCase):
    def test_real_duplicata(self):
        self.skipTest("o aceite real roda pelo worker na Tarefa 12, depois do merge do #21")


if __name__ == "__main__":
    unittest.main()
