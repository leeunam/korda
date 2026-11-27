"""Worker sem Docker: configuração e contexto falham cedo; classificação das falhas do dbt."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from korda_execution import worker
from korda_execution.harness.cliente_chat import ClienteChatFalso, RespostaChat
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
                self._executar(contexto=self.contexto)
        self._nada_foi_reservado()

    def test_chat_exige_o_contexto_do_plano(self):
        cfg = ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "chat", "KORDA_PERMITIR_LLM_REAL": "1",
                                         "KORDA_LLM_CHAVE": "fk-teste"})
        with self.assertRaisesRegex(worker.FalhaExecucao, "--contexto"):
            self._executar(cfg=cfg, cliente_llm=ClienteChatFalso([]))
        outro = copy.deepcopy(self.contexto)
        outro["revision"] += 1
        with self.assertRaisesRegex(worker.FalhaExecucao, "revisão"):
            self._executar(cfg=cfg, contexto=outro, cliente_llm=ClienteChatFalso([]))
        self._nada_foi_reservado()

    def test_agente_sdk_nao_constroi(self):
        cfg = ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "agente_sdk", "KORDA_PERMITIR_LLM_REAL": "1",
                                         "ANTHROPIC_API_KEY": "sk-teste"})
        with self.assertRaisesRegex(worker.FalhaExecucao, "Feita"):
            self._executar(cfg=cfg, contexto=self.contexto)
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


class TestPlanejamentoDevolvePerguntas(unittest.TestCase):
    """Com lacuna que impede construir, a LLM devolve perguntas e o worker para antes da sandbox."""

    def setUp(self):
        from korda_execution.aprovacoes import Registro

        self.plano, self.contexto = _plano_e_contexto()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.registro = Registro(self.base / "controle")
        self.registro.registrar(self.plano)
        self.registro.decidir_plano(self.plano["project_id"], self.plano["plan_version"], "Pessoa fictícia (teste)", True)
        sandbox = patch.object(worker, "LocalDockerSandbox")
        self.sandbox = sandbox.start()
        self.addCleanup(sandbox.stop)

    def _executar(self, texto):
        cliente = ClienteChatFalso([RespostaChat.texto(texto)])
        with self.assertRaises(worker.FalhaExecucao) as erro:
            worker.executar(self.registro, self.plano, "run-perguntas", raiz=self.base, fontes=self.base,
                            contexto=self.contexto, cfg=ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "falso"}),
                            cliente_llm=cliente)
        self.sandbox.assert_not_called()
        self.assertEqual(self.registro.consultar("run-perguntas")["state"], "falhou")
        return str(erro.exception)

    def test_lacuna_bloqueante_vira_perguntas_para_a_descoberta(self):
        pergunta = {"pergunta": "O OTIF conta entregas parciais?", "lacuna": "completude",
                    "metricas_afetadas": ["otif_pct"], "motivo": "sem regra no contexto"}
        bloco = json.dumps({"pronto_para_construir": False, "perguntas": [pergunta]}, ensure_ascii=False)
        mensagem = self._executar(f"## Modelos\n…\n```json\n{bloco}\n```")
        self.assertIn("contexto_insuficiente", mensagem)
        revisao = self.base / "revisao" / "run-perguntas"
        saida = json.loads((revisao / "perguntas.json").read_text(encoding="utf-8"))
        self.assertEqual(saida["perguntas"], [pergunta])
        self.assertEqual((saida["plan_version"], saida["context_id"], saida["context_revision"]),
                         (self.plano["plan_version"], self.plano["context_id"], self.plano["context_revision"]))
        self.assertTrue(saida["synthetic"])
        eventos = [json.loads(l) for l in (revisao / "eventos.jsonl").read_text().splitlines()]
        pedido = [e for e in eventos if e["type"] == "context_requested"]
        self.assertEqual(len(pedido), 1)
        self.assertEqual(pedido[0]["dados"]["perguntas"], [pergunta])
        self.assertTrue((revisao / "medicao.json").is_file())

    def test_sem_decisao_da_llm_nao_constroi(self):
        mensagem = self._executar("## Modelos\nsem bloco de decisão")
        self.assertIn("decisão", mensagem)
        self.assertFalse((self.base / "revisao" / "run-perguntas" / "perguntas.json").exists())


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
