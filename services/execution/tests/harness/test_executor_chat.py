"""ExecutorChat: construção + correção sobre chat/completions, com cliente falso (sem LLM)."""

import tempfile
import unittest
from pathlib import Path

from korda_execution.eventos import EmissorEventos
from korda_execution.harness.cliente_chat import ClienteChatFalso, RespostaChat
from korda_execution.harness.config import ConfigHarness
from korda_execution.harness.contexto import projetar_plano
from korda_execution.harness.executor_chat import ExecutorChat
from korda_execution.harness.medicao import Medidor
from korda_execution.harness.roteirizado import ConstrutorRoteirizado
from korda_execution.harness.tipos import Corretor

from .fakes import FerramentasFalsas

PLANO = {"plan_version": "a" * 64, "editable_models": ["models/*"], "limits": {"max_repair_attempts_per_step": 3},
         "rules": {"deduplicar_cte": True}, "metrics": {"custo_frete_por_entrega": {"formula": "f", "acceptance": []}},
         "tasks": [{"id": "bronze", "depends_on": [], "output": "o", "verify": "v"}]}
FALHA = {"ok": False, "codigo": "implementacao", "erro": "Failure in test chave_fiscal_unica"}
CARO = (200_000, 10_000)  # 1,00 USD por resposta a 4/20 USD por MTok


def _escreve(caminho, tokens=(1000, 200)):
    return RespostaChat.de_tool_calls([("escrever_modelo", {"caminho": caminho, "conteudo": "select 1"})], tokens=tokens)


class TestExecutorChat(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.emissor = EmissorEventos(Path(self.tmp.name) / "eventos.jsonl", "run-teste")
        self.medidor = Medidor("run-teste", "chat", "anthropic/claude-opus-5.5")
        self.f = FerramentasFalsas({}, ["models/*"])
        self.cfg = ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "chat", "KORDA_PERMITIR_LLM_REAL": "1",
                                              "KORDA_LLM_CHAVE": "fk-teste"})

    def tearDown(self):
        self.tmp.cleanup()

    def _executor(self, respostas):
        self.cliente = ClienteChatFalso(respostas)
        return ExecutorChat(self.cfg, self.cliente, self.f, projetar_plano(PLANO), {"cte": {}}, 3, self.emissor,
                            self.medidor)

    def test_constroi_varios_modelos(self):
        executor = self._executor([
            _escreve("models/bronze_ctes.sql"), _escreve("models/prata_ctes.sql"), _escreve("models/ouro_kpis.sql"),
            RespostaChat.de_tool_calls([("rodar_dbt", {"subcomando": "build"})]), RespostaChat.texto("pronto")])
        resultado = executor.construir("# Especificação")
        self.assertTrue(resultado["ok"])
        self.assertEqual(sorted(self.f.modelos), ["models/bronze_ctes.sql", "models/ouro_kpis.sql", "models/prata_ctes.sql"])
        self.assertIn("# Especificação", self.cliente.pedidos[0][1]["content"])
        self.assertEqual(self.medidor.resumo()["por_tentativa"][0]["tentativa"], 0)  # 0 = construção

    def test_construcao_sem_escrita_falha(self):
        resultado = self._executor([RespostaChat.texto("não sei")]).construir(None)
        self.assertFalse(resultado["ok"])
        self.assertIn("sem alteração", resultado["erro"])

    def test_tambem_e_um_corretor(self):
        executor = self._executor([_escreve("models/prata_ctes.sql"), RespostaChat.texto("ok")])
        self.assertIsInstance(executor, Corretor)
        resultado = executor(FALHA, 1)
        self.assertTrue(resultado["ok"])
        self.assertIn("tentativa 1 de 3", self.cliente.pedidos[0][1]["content"])
        self.assertIn("chave_fiscal_unica", self.cliente.pedidos[0][1]["content"])

    def test_teto_da_construcao_e_60_por_cento_com_folga(self):
        executor = self._executor([_escreve("models/a.sql", tokens=CARO) for _ in range(10)])
        executor.construir(None)
        # 8 × 0,6 × 0,9 = 4,32 → para depois da 5ª resposta de 1,00
        self.assertEqual(len(self.cliente.pedidos), 5)
        self.assertEqual(executor.ultima_saida.subtype, "error_max_budget_usd")

    def test_correcao_divide_o_restante_pelas_tentativas(self):
        executor = self._executor([])
        executor.gasto_usd = 5.0
        self.assertAlmostEqual(executor.teto_correcao(1), 3.0 / 3 * 0.9)
        self.assertAlmostEqual(executor.teto_correcao(3), 3.0 * 0.9)

    def test_orcamento_esgotado(self):
        executor = self._executor([_escreve("models/a.sql")])
        executor.gasto_usd = 8.0
        self.assertEqual(executor(FALHA, 1), {"ok": False, "erro": "orçamento de LLM esgotado", "custo_centavos": 0})
        self.assertFalse(executor.construir(None)["ok"])
        self.assertEqual(self.cliente.pedidos, [])

    def test_eventos_levam_o_custo_para_o_front(self):
        executor = self._executor([_escreve("models/a.sql"), RespostaChat.texto("ok"),
                                   _escreve("models/a.sql"), RespostaChat.texto("ok")])
        executor.construir(None)
        executor(FALHA, 1)
        fins = [e for e in self.emissor.ler() if e["type"] == "agent_finished"]
        self.assertEqual(len(fins), 2)
        dados = fins[-1]["dados"]
        self.assertEqual(dados["orcamento_centavos"], 4800)
        self.assertTrue(dados["custo_estimado"])
        self.assertEqual(dados["custo_total_centavos"],
                         fins[0]["dados"]["custo_centavos"] + fins[1]["dados"]["custo_centavos"])
        self.assertEqual(self.emissor.ler()[0]["type"], "build_started")

    def test_documento_base_desconta_do_orcamento_e_entra_no_custo_total(self):
        executor = self._executor([_escreve("models/a.sql"), RespostaChat.texto("ok")])
        executor.descontar_documento_base(0.5)
        executor.descontar_documento_base(None)
        self.assertAlmostEqual(executor.restante_usd, 7.5)
        self.assertAlmostEqual(executor.teto_construcao(), 4.8 * 0.9)
        executor.construir(None)
        fim = [e for e in self.emissor.ler() if e["type"] == "agent_finished"][0]["dados"]
        self.assertEqual(fim["custo_total_centavos"], 300 + fim["custo_centavos"])

    def test_custo_desconhecido_consome_o_teto(self):
        sem_uso = _escreve("models/a.sql")
        sem_uso.uso_informado = False
        executor = self._executor([sem_uso, RespostaChat.texto("ok")])
        resultado = executor.construir(None)
        self.assertIsNone(resultado["custo_centavos"])
        self.assertAlmostEqual(executor.gasto_usd, 8.0 * 0.6 * 0.9)


class TestConstrutorRoteirizado(unittest.TestCase):
    def test_copia_o_pipeline_feito_a_mao(self):
        f = FerramentasFalsas({}, ["models/*"])
        resultado = ConstrutorRoteirizado(f, {"models/a.sql": "select 1", "models/b.sql": "select 2"}).construir("doc")
        self.assertEqual(resultado, {"ok": True, "custo_centavos": 0})
        self.assertEqual(f.modelos, {"models/a.sql": "select 1", "models/b.sql": "select 2"})

    def test_escrita_recusada_falha(self):
        f = FerramentasFalsas({}, ["models/a.sql"])
        resultado = ConstrutorRoteirizado(f, {"models/a.sql": "x", "models/b.sql": "y"}).construir(None)
        self.assertFalse(resultado["ok"])
        self.assertIn("models/b.sql", resultado["erro"])


if __name__ == "__main__":
    unittest.main()
