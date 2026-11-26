"""Cliente chat/completions contra um servidor HTTP local falso (sem rede externa, sem LLM)."""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from korda_execution.harness.cliente_chat import ClienteChatFalso, ClienteChatHttp, ErroLLM, RespostaChat

FERRAMENTAS = [{"type": "function", "function": {"name": "ler_plano", "description": "x",
                                                  "parameters": {"type": "object", "properties": {}}}}]


class _Servidor:
    def __init__(self, status=200, corpo=None):
        self.recebidos = []
        servidor = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                tamanho = int(self.headers["Content-Length"])
                servidor.recebidos.append({"path": self.path, "headers": dict(self.headers),
                                           "body": json.loads(self.rfile.read(tamanho))})
                dados = json.dumps(corpo).encode() if not isinstance(corpo, bytes) else corpo
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(dados)

            def log_message(self, *a):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/gateway/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def fechar(self):
        self.httpd.shutdown()
        self.httpd.server_close()


RESPOSTA_TOOL = {
    "choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": "call_1", "type": "function", "function": {"name": "ler_plano", "arguments": "{}"}}]}}],
    "usage": {"prompt_tokens": 1200, "completion_tokens": 80},
}


class TestClienteChatHttp(unittest.TestCase):
    def _cliente(self, servidor):
        # O teste usa http local; em produção a config exige https.
        return ClienteChatHttp(servidor.url, "fk-teste", "anthropic/claude-opus-5.5", timeout_s=5)

    def test_envia_formato_openai_e_le_tool_calls(self):
        s = _Servidor(corpo=RESPOSTA_TOOL)
        try:
            resposta = self._cliente(s).completar([{"role": "user", "content": "oi"}], FERRAMENTAS)
        finally:
            s.fechar()
        pedido = s.recebidos[0]
        self.assertEqual(pedido["path"], "/gateway/v1/chat/completions")
        self.assertEqual(pedido["headers"]["Authorization"], "Bearer fk-teste")
        self.assertEqual(pedido["body"]["model"], "anthropic/claude-opus-5.5")
        self.assertEqual(pedido["body"]["tools"], FERRAMENTAS)
        self.assertEqual(pedido["body"]["messages"], [{"role": "user", "content": "oi"}])
        self.assertIsInstance(resposta, RespostaChat)
        self.assertEqual(resposta.tool_calls, [{"id": "call_1", "nome": "ler_plano", "argumentos": "{}"}])
        self.assertEqual((resposta.tokens_entrada, resposta.tokens_saida), (1200, 80))
        self.assertTrue(resposta.uso_informado)
        self.assertEqual(resposta.mensagem_assistente["tool_calls"][0]["id"], "call_1")

    def test_resposta_sem_usage(self):
        corpo = {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "pronto"}}]}
        s = _Servidor(corpo=corpo)
        try:
            resposta = self._cliente(s).completar([{"role": "user", "content": "oi"}], FERRAMENTAS)
        finally:
            s.fechar()
        self.assertEqual(resposta.conteudo, "pronto")
        self.assertEqual(resposta.tool_calls, [])
        self.assertFalse(resposta.uso_informado)

    def test_erro_http_nao_vaza_a_chave(self):
        s = _Servidor(status=401, corpo={"error": "chave inválida"})
        try:
            with self.assertRaises(ErroLLM) as ctx:
                self._cliente(s).completar([{"role": "user", "content": "oi"}], FERRAMENTAS)
        finally:
            s.fechar()
        self.assertIn("401", str(ctx.exception))
        self.assertNotIn("fk-teste", str(ctx.exception))

    def test_resposta_invalida(self):
        s = _Servidor(corpo=b"<html>erro</html>")
        try:
            with self.assertRaises(ErroLLM):
                self._cliente(s).completar([{"role": "user", "content": "oi"}], FERRAMENTAS)
        finally:
            s.fechar()

    def test_chave_nao_aparece_no_repr(self):
        self.assertNotIn("fk-teste", repr(ClienteChatHttp("https://x/v1", "fk-teste", "m")))


class TestClienteChatFalso(unittest.TestCase):
    def test_devolve_respostas_em_ordem_e_registra_pedidos(self):
        falso = ClienteChatFalso([RespostaChat.de_tool_calls([("ler_plano", {})]), RespostaChat.texto("fim")])
        primeira = falso.completar([{"role": "user", "content": "a"}], FERRAMENTAS)
        segunda = falso.completar([{"role": "user", "content": "b"}], FERRAMENTAS)
        self.assertEqual(primeira.tool_calls[0]["nome"], "ler_plano")
        self.assertEqual(segunda.conteudo, "fim")
        self.assertEqual(len(falso.pedidos), 2)
        self.assertEqual(falso.completar([], FERRAMENTAS).conteudo, "")  # roteiro esgotado: para


if __name__ == "__main__":
    unittest.main()
