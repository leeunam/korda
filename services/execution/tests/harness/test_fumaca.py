"""Teste de fumaça do gateway: só a lógica, com cliente falso (sem LLM)."""

import unittest

from korda_execution.harness.cliente_chat import ClienteChatFalso, RespostaChat
from korda_execution.harness.fumaca import testar_gateway


class TestFumaca(unittest.TestCase):
    def test_gateway_compativel(self):
        cliente = ClienteChatFalso([RespostaChat.de_tool_calls([("ping", {"texto": "ok"})]), RespostaChat.texto("pong")])
        r = testar_gateway(cliente, precos=(4.0, 20.0))
        self.assertTrue(r["tool_calls"])
        self.assertTrue(r["argumentos_validos"])
        self.assertTrue(r["aceita_mensagem_tool"])
        self.assertTrue(r["usage"])
        self.assertTrue(r["compativel"])
        self.assertEqual(r["chamadas"], 2)
        mensagens = cliente.pedidos[1]
        self.assertEqual(mensagens[-1]["role"], "tool")

    def test_sem_tool_calls_para_na_primeira_chamada(self):
        cliente = ClienteChatFalso([RespostaChat.texto("não uso ferramentas")])
        r = testar_gateway(cliente, precos=(4.0, 20.0))
        self.assertFalse(r["tool_calls"])
        self.assertFalse(r["compativel"])
        self.assertEqual(r["chamadas"], 1)


if __name__ == "__main__":
    unittest.main()
