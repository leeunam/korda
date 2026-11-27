"""Comando planejar: a LLM do planejamento gera a construção ou as perguntas (cliente falso, sem LLM)."""

import copy
import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

from korda_execution import planejamento
from korda_execution.harness.cliente_chat import ClienteChatFalso, RespostaChat
from korda_execution.harness.config import ConfigHarness
from korda_execution.worker import FalhaExecucao

REPO = Path(__file__).resolve().parents[3]
CONTEXTO = REPO / "packages/contracts/context/v0.1.0/examples/02_rateio_confirmado.json"
DOC = "## Modelos\nprata_ctes\n## Regras aplicadas\n…\n## Métricas\n…\n## Testes de aceite\n…\n## Premissas e lacunas\n…"
PERGUNTA = {"pergunta": "O OTIF conta entregas parciais?", "lacuna": "completude",
            "metricas_afetadas": ["otif_pct"], "motivo": "sem regra no contexto"}
FALSO = ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "falso"})


def _decisao(pronto, perguntas=()):
    bloco = json.dumps({"pronto_para_construir": pronto, "perguntas": list(perguntas)}, ensure_ascii=False)
    return f"{DOC}\n\n```json\n{bloco}\n```\n"


class TestPlanejar(unittest.TestCase):
    def setUp(self):
        from services.planning.korda_planning import gerar_plano

        self.contexto = json.loads(CONTEXTO.read_text(encoding="utf-8"))
        self.plano = gerar_plano(self.contexto, destino="pasta-demo", custo_estimado_centavos=0)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)

    def _planejar(self, texto, cfg=FALSO, plano=None, contexto=None, finish_reason="stop"):
        resposta = dataclasses.replace(RespostaChat.texto(texto, tokens=(4000, 2500)), finish_reason=finish_reason)
        self.cliente = ClienteChatFalso([resposta])
        return planejamento.planejar(plano or self.plano, contexto or self.contexto, raiz=self.raiz, cfg=cfg,
                                     cliente_llm=self.cliente)

    def test_pronto_gera_plano_com_construcao_aprovavel(self):
        from services.planning.korda_planning import validar_plano

        r = self._planejar(_decisao(True))
        self.assertEqual(r["estado"], "pronto")
        plano = r["plano"]
        validar_plano(plano)
        self.assertNotEqual(plano["plan_version"], self.plano["plan_version"])
        self.assertEqual(plano["construction"]["document"].strip(), DOC)
        self.assertTrue(plano["construction"]["synthetic"])
        pasta = Path(r["pasta"])
        self.assertEqual(json.loads((pasta / "plano.json").read_text()), plano)
        self.assertNotIn("pronto_para_construir", (pasta / "documento_base.md").read_text())
        medicao = json.loads((pasta / "medicao.json").read_text())
        self.assertEqual((medicao["tokens_entrada"], medicao["tokens_saida"]), (4000, 2500))
        self.assertTrue(medicao["synthetic"])
        self.assertEqual(medicao["precos"], {"entrada_usd_mtok": 4.0, "saida_usd_mtok": 20.0, "taxa_usd_brl": 6.0})
        self.assertEqual(len(self.cliente.pedidos), 1)  # uma única chamada

    def test_lacuna_gera_perguntas_sem_plano(self):
        r = self._planejar(_decisao(False, [PERGUNTA]))
        self.assertEqual(r["estado"], "perguntas")
        self.assertEqual(r["perguntas"], [PERGUNTA])
        pasta = Path(r["pasta"])
        saida = json.loads((pasta / "perguntas.json").read_text())
        self.assertEqual(saida["perguntas"], [PERGUNTA])
        self.assertEqual((saida["plan_version"], saida["context_id"], saida["context_revision"]),
                         (self.plano["plan_version"], self.plano["context_id"], self.plano["context_revision"]))
        self.assertFalse((pasta / "plano.json").exists())

    def test_sem_decisao_e_erro_e_nao_gera_plano(self):
        with self.assertRaisesRegex(FalhaExecucao, "decisão"):
            self._planejar(DOC)
        pastas = list((self.raiz / "planejamento").iterdir())
        self.assertEqual(len(pastas), 1)
        self.assertTrue((pastas[0] / "documento_base.md").is_file())
        self.assertFalse((pastas[0] / "plano.json").exists())

    def test_resposta_cortada_e_erro_proprio_mesmo_com_decisao(self):
        # a decisão vem no início; um corte no fim ainda deixa o documento incompleto
        with self.assertRaisesRegex(FalhaExecucao, f"cortada no limite de {planejamento.MAX_TOKENS_PLANEJAMENTO} tokens"):
            self._planejar(_decisao(True), finish_reason="length")
        pasta = next((self.raiz / "planejamento").iterdir())
        medicao = json.loads((pasta / "medicao.json").read_text())
        self.assertEqual(medicao["finish_reason"], "length")
        self.assertTrue((pasta / "resposta.json").is_file())
        self.assertFalse((pasta / "plano.json").exists())

    def test_teto_de_saida(self):
        self.assertEqual(planejamento.MAX_TOKENS_PLANEJAMENTO, 8000)

    def test_plano_b_e_sdk_nao_planejam(self):
        for env in ({"KORDA_EXECUTOR": "roteirizado"},
                    {"KORDA_EXECUTOR": "agente_sdk", "KORDA_PERMITIR_LLM_REAL": "1", "ANTHROPIC_API_KEY": "sk-teste"}):
            with self.subTest(env=env), self.assertRaisesRegex(FalhaExecucao, "Feita"):
                self._planejar(_decisao(True), cfg=ConfigHarness.de_ambiente(env))
        self.assertFalse((self.raiz / "planejamento").exists())

    def test_contexto_de_outra_revisao_ou_plano_ja_planejado(self):
        outro = copy.deepcopy(self.contexto)
        outro["revision"] += 1
        with self.assertRaisesRegex(FalhaExecucao, "revisão"):
            self._planejar(_decisao(True), contexto=outro)
        planejado = self._planejar(_decisao(True))["plano"]
        with self.assertRaisesRegex(FalhaExecucao, "construção"):
            self._planejar(_decisao(True), plano=planejado)

    def test_falha_ou_documento_vazio_preserva_medicao_do_planejamento(self):
        cliente = ClienteChatFalso([RespostaChat.texto("", tokens=(160, 4))])
        with self.assertRaisesRegex(ValueError, "documento-base vazio"):
            planejamento.planejar(self.plano, self.contexto, raiz=self.raiz, cfg=FALSO, cliente_llm=cliente)
        (pasta,) = (self.raiz / "planejamento").iterdir()
        medicao = json.loads((pasta / "medicao.json").read_text())
        self.assertEqual((medicao["tokens_entrada"], medicao["tokens_saida"]), (160, 4))
        self.assertTrue(medicao["custo_completo"])
        self.assertGreater(medicao["custo_usd"], 0)
        self.assertFalse((pasta / "plano.json").exists())

    def test_planejamento_recusa_uso_desconhecido_e_preserva_tentativa(self):
        resposta = RespostaChat.texto(_decisao(True))
        resposta.uso_informado = False
        with self.assertRaisesRegex(FalhaExecucao, "orçamento"):
            planejamento.planejar(self.plano, self.contexto, raiz=self.raiz, cfg=FALSO, cliente_llm=ClienteChatFalso([resposta]))
        (pasta,) = (self.raiz / "planejamento").iterdir()
        medicao = json.loads((pasta / "medicao.json").read_text())
        self.assertFalse(medicao["custo_completo"])
        self.assertIsNone(medicao["custo_usd"])
        self.assertFalse((pasta / "plano.json").exists())

    def test_planejamento_com_saldo_insuficiente_nao_envia_pedido(self):
        cfg = ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "falso", "KORDA_ORCAMENTO_EXECUCAO_USD": "0.00001"})
        cliente = ClienteChatFalso([])
        with self.assertRaises(FalhaExecucao):
            planejamento.planejar(self.plano, self.contexto, raiz=self.raiz, cfg=cfg, cliente_llm=cliente)
        self.assertFalse(cliente.pedidos)
        (pasta,) = (self.raiz / "planejamento").iterdir()
        self.assertEqual(json.loads((pasta / "medicao.json").read_text())["chamadas"], 0)

    def test_contexto_com_mesma_identidade_mas_outro_conteudo_e_recusado(self):
        outro = copy.deepcopy(self.contexto)
        outro["evidence"][0]["excerpt"] += " Texto divergente."
        with self.assertRaisesRegex(FalhaExecucao, "revisão"):
            self._planejar(_decisao(True), contexto=outro)
        self.assertFalse(self.cliente.pedidos)

    def test_falso_exige_cliente(self):
        with self.assertRaisesRegex(FalhaExecucao, "só para testes"):
            planejamento.planejar(self.plano, self.contexto, raiz=self.raiz, cfg=FALSO)


if __name__ == "__main__":
    unittest.main()
