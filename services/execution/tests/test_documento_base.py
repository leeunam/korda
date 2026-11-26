"""Documento-base: a chamada de API do worker que gera a especificação para o harness (sem LLM)."""

import json
import unittest
from pathlib import Path

from korda_execution.documento_base import SECOES, SISTEMA_DOCUMENTO, gerar_documento_base
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


if __name__ == "__main__":
    unittest.main()
