"""Contrato público do worker e fixtures de planejamento e chat sem rede."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from jsonschema.exceptions import ValidationError

from korda_execution import worker
from korda_execution.aprovacoes import ErroAprovacao, Registro
from korda_execution.harness.cliente_chat import ClienteChatFalso, RespostaChat
from korda_execution.harness.config import ConfigHarness, ErroConfiguracao
from korda_execution.planejamento import planejar

REPO = Path(__file__).resolve().parents[3]
PROJETO = REPO / "services/execution/pipeline/projeto"
CONTEXTO = REPO / "packages/contracts/context/v0.1.0/examples/02_rateio_confirmado.json"
FALSO = ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "falso"})
ROTEIRIZADO = ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "roteirizado"})
DOCUMENTO = """## Modelos
Construir prata_ctes e prata_rateios, ouro_por_pedido, ouro_por_viagem e ouro_kpis.
## Regras aplicadas
Deduplicar a chave do CT-e e aplicar o rateio confirmado na descoberta.
## Métricas
Calcular custo de frete por entrega, OTIF e ocupação.
## Testes de aceite
Conservar os centavos e produzir uma linha por pedido e por viagem.
## Premissas e lacunas
Usar o lote aprovado para a 01_demo."""


def planejar_com_cliente_falso(plano_base, contexto, raiz, perguntas=()):
    decisao = {"pronto_para_construir": not perguntas, "perguntas": list(perguntas)}
    texto = DOCUMENTO + "\n\n```json\n" + json.dumps(decisao, ensure_ascii=False) + "\n```\n"
    cliente = ClienteChatFalso([RespostaChat.texto(texto, tokens=(42, 31))])
    resultado = planejar(plano_base, contexto, raiz=raiz, cfg=FALSO, cliente_llm=cliente)
    if len(cliente.pedidos) != 1:
        raise AssertionError("O planejamento deve consultar seu cliente uma única vez")
    return resultado


def modelos_de_referencia():
    return {p.relative_to(PROJETO).as_posix(): p.read_text(encoding="utf-8")
            for p in sorted((PROJETO / "models").rglob("*.sql"))}


def escrever(modelos):
    return RespostaChat.de_tool_calls(
        [("escrever_modelo", {"caminho": caminho, "conteudo": sql}) for caminho, sql in sorted(modelos.items())],
        tokens=(0, 0),
    )


class TestWorkerFalhaCedo(unittest.TestCase):
    def setUp(self):
        from services.planning.korda_planning import gerar_plano

        self.contexto = json.loads(CONTEXTO.read_text(encoding="utf-8"))
        self.plano = gerar_plano(self.contexto, destino="pasta-demo", custo_estimado_centavos=0)
        self.registro = Mock(spec=Registro)
        temporario = tempfile.TemporaryDirectory()
        self.addCleanup(temporario.cleanup)
        self.raiz = Path(temporario.name)
        self.sandbox = self.enterContext(patch.object(worker, "LocalDockerSandbox"))

    def _executar(self, **kw):
        return worker.executar(self.registro, self.plano, "run-cedo", raiz=self.raiz,
                               fontes=self.raiz / "fontes-ainda-fechadas", **kw)

    def _nada_foi_reservado(self):
        self.registro.iniciar.assert_not_called()
        self.sandbox.assert_not_called()
        self.assertFalse((self.raiz / "revisao").exists())

    def test_executor_com_llm_sem_autorizacao_falha_antes_da_sandbox(self):
        with patch.dict("os.environ", {"KORDA_EXECUTOR": "chat", "KORDA_PERMITIR_LLM_REAL": "",
                                       "KORDA_LLM_CHAVE": ""}):
            with self.assertRaises(ErroConfiguracao):
                self._executar()
        self._nada_foi_reservado()

    def test_chat_e_falso_exigem_construcao_antes_do_gate(self):
        chat = ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "chat", "KORDA_PERMITIR_LLM_REAL": "1",
                                          "KORDA_LLM_CHAVE": "credencial-ficticia-do-teste"})
        for cfg in (chat, FALSO):
            with self.subTest(executor=cfg.executor), self.assertRaisesRegex(ValueError, "planejar|construção"):
                self._executar(cfg=cfg, cliente_llm=ClienteChatFalso([]))
            self._nada_foi_reservado()

    def test_falso_precisa_de_cliente_e_sdk_nao_constroi(self):
        self.plano = planejar_com_cliente_falso(self.plano, self.contexto, self.raiz)["plano"]
        sdk = ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "agente_sdk", "KORDA_PERMITIR_LLM_REAL": "1",
                                         "ANTHROPIC_API_KEY": "credencial-ficticia-do-teste"})
        for cfg, mensagem in ((FALSO, "falso|teste"), (sdk, "agente_sdk|Feita")):
            with self.subTest(executor=cfg.executor), self.assertRaisesRegex(ValueError, mensagem):
                self._executar(cfg=cfg)
            self._nada_foi_reservado()

    def test_plano_com_modelos_fora_do_escopo_e_recusado(self):
        for modelos, erro in (([], ValueError), (["tests/*"], ValidationError)):
            with self.subTest(modelos=modelos), self.assertRaises(erro):
                self.plano["editable_models"] = modelos
                self._executar(cfg=ROTEIRIZADO)
            self._nada_foi_reservado()

    def test_perguntas_voltam_a_descoberta_e_aprovacao_base_nao_autoriza_construcao(self):
        pergunta = {"pergunta": "O OTIF conta entregas parciais?", "lacuna": "completude",
                    "metricas_afetadas": ["otif_pct"], "motivo": "confirmar regra da métrica"}
        pendente = planejar_com_cliente_falso(self.plano, self.contexto, self.raiz, [pergunta])
        self.assertEqual(pendente["estado"], "perguntas")
        pasta = Path(pendente["pasta"])
        self.assertEqual(json.loads((pasta / "perguntas.json").read_text())["perguntas"], [pergunta])
        self.assertFalse((pasta / "plano.json").exists())
        self._nada_foi_reservado()

        self.registro = Registro(self.raiz / "controle")
        self.registro.registrar(self.plano)
        self.registro.decidir_plano(self.plano["project_id"], self.plano["plan_version"], "Revisor fictício", True)
        pronto = planejar_com_cliente_falso(self.plano, self.contexto, self.raiz)
        self.assertEqual(pronto["estado"], "pronto")
        self.assertNotEqual(pronto["plano"]["plan_version"], self.plano["plan_version"])
        self.plano = pronto["plano"]
        self.registro.registrar(self.plano)
        with self.assertRaises(ErroAprovacao):
            self._executar(cfg=FALSO, cliente_llm=ClienteChatFalso([]))
        self.sandbox.assert_not_called()
        self.assertFalse((self.raiz / "revisao").exists())


class TestClassificacao(unittest.TestCase):
    def test_classificacao_usada_na_etapa_de_build(self):
        casos = [
            ({"codigo": 1}, "implementacao"), ({"codigo": 2}, "implementacao"),
            ({"codigo": 1, "stdout": "Failure in test integridade_fontes (tests/integridade_fontes.sql)"}, "dados"),
            ({"codigo": 1, "estourou_tempo": True}, "tecnico"), ({"codigo": 125}, "tecnico"),
            ({"codigo": 126}, "tecnico"), ({"codigo": 137}, "tecnico"), ({"codigo": -9}, "tecnico"),
        ]
        for resultado, classe in casos:
            with self.subTest(resultado=resultado):
                self.assertEqual(worker.classificar_falha_dbt({"ok": False, **resultado}), classe)

    def test_modelos_a_mao_disponiveis_ao_executor_roteirizado(self):
        self.assertEqual(worker.modelos_a_mao(), modelos_de_referencia())
        self.assertIn(worker.MODELO_CTE, worker.modelos_a_mao())


if __name__ == "__main__":
    unittest.main()
