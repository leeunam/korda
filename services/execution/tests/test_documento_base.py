"""Documento-base: a chamada de API do worker que gera a especificação para o harness (sem LLM)."""

import json
import unittest
from pathlib import Path

from korda_execution.documento_base import SECOES, SISTEMA_DOCUMENTO, gerar_documento_base, ler_decisao, remover_bloco_decisao
from korda_execution.harness.cliente_chat import ClienteChatFalso, ErroLLM, RespostaChat

RAIZ = Path(__file__).resolve().parents[3]
CONTEXTO = json.loads((RAIZ / "packages/contracts/context/v0.1.0/examples/02_rateio_confirmado.json").read_text())
PLANO = {"plan_version": "a" * 64, "editable_models": ["models/*"], "limits": {}, "rules": {"rateio_cte": "peso"},
         "metrics": {"otif_pct": {"formula": "no prazo e completo / elegíveis"}}, "tasks": []}
PRECOS = (4.0, 20.0)
DOC = "\n\n".join(f"## {s}\n..." for s in SECOES)


class TestDocumentoBase(unittest.TestCase):
    def test_envia_contexto_e_plano_sem_ferramentas(self):
        cliente = ClienteChatFalso([RespostaChat.texto(DOC, tokens=(10_000, 2_000))])
        doc = gerar_documento_base(cliente, CONTEXTO, PLANO, precos=PRECOS)
        mensagens = cliente.pedidos[0]
        self.assertEqual(mensagens[0], {"role": "system", "content": SISTEMA_DOCUMENTO})
        self.assertIn("ctx-demo-01", mensagens[1]["content"])
        self.assertIn("no prazo e completo", mensagens[1]["content"])
        self.assertEqual(doc.texto, DOC)
        self.assertAlmostEqual(doc.custo_usd, (10_000 * 4 + 2_000 * 20) / 1e6)
        self.assertEqual(doc.secoes_ausentes, [])

    def test_sistema_proibe_inventar(self):
        for trecho in ("lacuna", "não invente", "evidência"):
            self.assertIn(trecho, SISTEMA_DOCUMENTO.lower())

    def test_aponta_secoes_ausentes(self):
        cliente = ClienteChatFalso([RespostaChat.texto("## Modelos\nsó isso")])
        doc = gerar_documento_base(cliente, CONTEXTO, PLANO, precos=PRECOS)
        self.assertIn("Testes de aceite", doc.secoes_ausentes)

    def test_resposta_vazia_e_erro(self):
        with self.assertRaises(ValueError):
            gerar_documento_base(ClienteChatFalso([RespostaChat.texto("   ")]), CONTEXTO, PLANO, precos=PRECOS)

    def test_erro_da_api_propaga(self):
        class Falha:
            def completar(self, *a):
                raise ErroLLM("HTTP 500")
        with self.assertRaises(ErroLLM):
            gerar_documento_base(Falha(), CONTEXTO, PLANO, precos=PRECOS)

    def test_sem_usage_custo_desconhecido(self):
        resposta = RespostaChat.texto(DOC)
        resposta.uso_informado = False
        self.assertIsNone(gerar_documento_base(ClienteChatFalso([resposta]), CONTEXTO, PLANO, precos=PRECOS).custo_usd)



def _bloco(objeto):
    return "\n```json\n" + json.dumps(objeto, ensure_ascii=False) + "\n```\n"


PERGUNTA = {"pergunta": "O OTIF conta entregas parciais?", "lacuna": "completude",
            "metricas_afetadas": ["otif_pct"], "motivo": "sem regra de completude no contexto"}


class TestDecisaoDoPlanejamento(unittest.TestCase):
    """A LLM do planejamento diz se dá para construir; se não, gera as perguntas para a descoberta."""

    def test_decisao_pronta_com_perguntas_pendentes_e_invalida(self):
        texto = DOC + _bloco({"pronto_para_construir": True, "perguntas": [PERGUNTA]})
        self.assertEqual(ler_decisao(texto), (None, []))

    def test_pronto_sem_perguntas(self):
        self.assertEqual(ler_decisao(DOC + _bloco({"pronto_para_construir": True, "perguntas": []})), (True, []))

    def test_lacuna_bloqueante_devolve_perguntas(self):
        pronto, perguntas = ler_decisao(DOC + _bloco({"pronto_para_construir": False, "perguntas": [PERGUNTA]}))
        self.assertIs(pronto, False)
        self.assertEqual(perguntas, [PERGUNTA])

    def test_usa_o_ultimo_bloco_json(self):
        texto = DOC + _bloco({"exemplo": 1}) + _bloco({"pronto_para_construir": True, "perguntas": []})
        self.assertEqual(ler_decisao(texto), (True, []))

    def test_bloco_ausente_ou_invalido_nao_decide(self):
        for texto in (DOC, DOC + "\n```json\n{quebrado\n```",
                      DOC + _bloco({"pronto_para_construir": "sim", "perguntas": []}),
                      DOC + _bloco({"pronto_para_construir": False, "perguntas": "x"}),
                      DOC + _bloco({"pronto_para_construir": False, "perguntas": [{"lacuna": "sem pergunta"}]}),
                      DOC + _bloco({"pronto_para_construir": False, "perguntas": []}),
                      DOC + _bloco([1, 2])):
            with self.subTest(texto=texto[-80:]):
                self.assertEqual(ler_decisao(texto), (None, []))

    def test_limita_perguntas_e_campos(self):
        muitas = [{**PERGUNTA, "extra": "x", "pergunta": f"P{i}?"} for i in range(30)]
        pronto, perguntas = ler_decisao(DOC + _bloco({"pronto_para_construir": False, "perguntas": muitas}))
        self.assertEqual(len(perguntas), 20)
        self.assertNotIn("extra", perguntas[0])

    def test_documento_gerado_traz_a_decisao(self):
        texto = DOC + _bloco({"pronto_para_construir": False, "perguntas": [PERGUNTA]})
        doc = gerar_documento_base(ClienteChatFalso([RespostaChat.texto(texto)]), CONTEXTO, PLANO, precos=PRECOS)
        self.assertIs(doc.pronto_para_construir, False)
        self.assertEqual(doc.perguntas, [PERGUNTA])

    def test_remove_so_o_bloco_de_decisao(self):
        texto = DOC + _bloco({"exemplo": 1}) + _bloco({"pronto_para_construir": True, "perguntas": []})
        limpo = remover_bloco_decisao(texto)
        self.assertNotIn("pronto_para_construir", limpo)
        self.assertIn('"exemplo"', limpo)
        self.assertTrue(limpo.startswith(DOC))

    def test_sistema_pede_o_bloco_de_decisao(self):
        for trecho in ("pronto_para_construir", "perguntas", "```json"):
            self.assertIn(trecho, SISTEMA_DOCUMENTO)


if __name__ == "__main__":
    unittest.main()
