"""Worker sem Docker: configuração e construção aprovada falham cedo; classificação das falhas do dbt."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from korda_execution import worker
from korda_execution.harness.cliente_chat import ClienteChatFalso
from korda_execution.harness.config import ConfigHarness, ErroConfiguracao

REPO = Path(__file__).resolve().parents[3]
CONTEXTO = REPO / "packages/contracts/context/v0.1.0/examples/02_rateio_confirmado.json"


def _plano_e_contexto():
    from services.planning.korda_planning import gerar_plano

    contexto = json.loads(CONTEXTO.read_text(encoding="utf-8"))
    return gerar_plano(contexto, destino="pasta-demo", custo_estimado_centavos=0), contexto


class TestWorkerFalhaCedo(unittest.TestCase):
    def setUp(self):
        self.plano, self.contexto = _plano_e_contexto()
        self.registro = Mock()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        sandbox = patch.object(worker, "LocalDockerSandbox")
        self.sandbox = sandbox.start()
        self.addCleanup(sandbox.stop)

    def _executar(self, **kw):
        return worker.executar(self.registro, self.plano, "run-cedo", raiz=Path(self.tmp.name),
                               fontes=Path(self.tmp.name), **kw)

    def _nada_foi_reservado(self):
        self.registro.iniciar.assert_not_called()
        self.sandbox.assert_not_called()
        self.assertFalse((Path(self.tmp.name) / "revisao").exists())

    def test_executor_com_llm_sem_autorizacao_falha_antes_da_sandbox(self):
        with patch.dict("os.environ", {"KORDA_EXECUTOR": "chat", "KORDA_PERMITIR_LLM_REAL": "",
                                       "KORDA_LLM_CHAVE": ""}):
            with self.assertRaises(ErroConfiguracao):
                self._executar()
        self._nada_foi_reservado()

    def test_chat_exige_a_construcao_aprovada(self):
        cfg = ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "chat", "KORDA_PERMITIR_LLM_REAL": "1",
                                         "KORDA_LLM_CHAVE": "fk-teste"})
        with self.assertRaisesRegex(worker.FalhaExecucao, "planejar"):
            self._executar(cfg=cfg, cliente_llm=ClienteChatFalso([]))
        self._nada_foi_reservado()

    def test_agente_sdk_nao_constroi(self):
        cfg = ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "agente_sdk", "KORDA_PERMITIR_LLM_REAL": "1",
                                         "ANTHROPIC_API_KEY": "sk-teste"})
        with self.assertRaisesRegex(worker.FalhaExecucao, "Feita"):
            self._executar(cfg=cfg)
        self._nada_foi_reservado()

    def test_falso_so_com_cliente_de_teste(self):
        with self.assertRaisesRegex(worker.FalhaExecucao, "só para testes"):
            self._executar(cfg=ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "falso"}))
        self._nada_foi_reservado()

    def test_plano_sem_modelos_autorizados(self):
        with patch.object(worker, "validar_plano"):
            self.plano["editable_models"] = []
            with self.assertRaisesRegex(worker.FalhaExecucao, "nenhum modelo"):
                self._executar(cfg=ConfigHarness.de_ambiente({}))
            self.plano["editable_models"] = ["tests/*"]
            with self.assertRaises(worker.FalhaExecucao):
                self._executar(cfg=ConfigHarness.de_ambiente({}))
        self._nada_foi_reservado()


class TestClassificacao(unittest.TestCase):
    def test_falha_de_modelo_ou_compilacao_e_do_agente(self):
        for codigo in (1, 2):
            self.assertEqual(worker.classificar_falha_dbt({"ok": False, "codigo": codigo}), "implementacao")

    def test_infraestrutura_escala_direto(self):
        for resultado in ({"codigo": 137, "estourou_tempo": True}, {"codigo": 1, "estourou_tempo": True},
                          {"codigo": 125}, {"codigo": 126}, {"codigo": -9}):
            with self.subTest(resultado=resultado):
                self.assertEqual(worker.classificar_falha_dbt({"ok": False, **resultado}), "tecnico")


class TestPlanoB(unittest.TestCase):
    def test_pipeline_a_mao_fica_no_host_para_o_roteirizado(self):
        modelos = worker.modelos_a_mao()
        self.assertIn(worker.MODELO_CTE, modelos)
        self.assertTrue(all(c.startswith("models/") and c.endswith(".sql") for c in modelos))


if __name__ == "__main__":
    unittest.main()
