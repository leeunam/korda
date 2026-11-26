"""Loop de ferramentas sobre chat/completions, com cliente falso (sem LLM)."""

import json
import tempfile
import unittest
from pathlib import Path

from korda_execution.eventos import EmissorEventos
from korda_execution.harness.cliente_chat import ClienteChatFalso, ErroLLM, RespostaChat
from korda_execution.harness.sessao_chat import ferramentas_openai, executar_sessao

from .fakes import FerramentasFalsas

MODELO = "models/prata_ctes.sql"
PRECOS = (4.0, 20.0)  # USD por milhão de tokens


class _ClienteQueFalha:
    def __init__(self, antes):
        self.antes = list(antes)

    def completar(self, mensagens, ferramentas):
        if self.antes:
            return self.antes.pop(0)
        raise ErroLLM("API do LLM respondeu HTTP 500")


class TestSessaoChat(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.emissor = EmissorEventos(Path(self.tmp.name) / "eventos.jsonl", "run-teste")
        self.f = FerramentasFalsas({MODELO: "select 1"}, ["models/*"])

    def tearDown(self):
        self.tmp.cleanup()

    def _sessao(self, cliente, max_turnos=10, teto=5.0):
        return executar_sessao(cliente, "sistema", "construa", self.f, ["models/*"], emissor=self.emissor,
                               tentativa=1, max_turnos=max_turnos, teto_usd=teto, precos=PRECOS)

    def test_ferramentas_no_formato_openai(self):
        nomes = [t["function"]["name"] for t in ferramentas_openai()]
        self.assertEqual(len(nomes), 6)
        self.assertIn("escrever_modelo", nomes)
        self.assertTrue(all(t["type"] == "function" for t in ferramentas_openai()))

    def test_executa_ferramentas_e_devolve_resultados_ao_modelo(self):
        cliente = ClienteChatFalso([
            RespostaChat.de_tool_calls([("ler_arquivo", {"caminho": MODELO}),
                                        ("escrever_modelo", {"caminho": "models/prata_novo.sql", "conteudo": "select 2"})]),
            RespostaChat.de_tool_calls([("rodar_dbt", {"subcomando": "build"})]),
            RespostaChat.texto("pronto"),
        ])
        saida, escritas = self._sessao(cliente)
        self.assertEqual(saida.subtype, "success")
        self.assertEqual(saida.num_turns, 3)
        self.assertEqual(escritas, ["models/prata_novo.sql"])
        self.assertEqual(self.f.modelos["models/prata_novo.sql"], "select 2")
        mensagens = cliente.pedidos[1]
        respostas_tool = [m for m in mensagens if m["role"] == "tool"]
        self.assertEqual([m["tool_call_id"] for m in respostas_tool], ["call_0", "call_1"])
        self.assertTrue(json.loads(respostas_tool[1]["content"])["ok"])
        self.assertEqual(mensagens[0], {"role": "system", "content": "sistema"})
        # custo estimado: 2×(1000 in, 200 out) + (100 in, 20 out) a 4/20 USD por MTok
        self.assertAlmostEqual(saida.total_cost_usd, (2100 * 4 + 420 * 20) / 1e6)
        self.assertEqual(saida.usage, {"input_tokens": 2100, "output_tokens": 420})

    def test_politica_recusa_e_avisa_o_modelo(self):
        cliente = ClienteChatFalso([
            RespostaChat.de_tool_calls([("escrever_modelo", {"caminho": "tests/chave.sql", "conteudo": "x"}),
                                        ("Bash", {"command": "ls"})]),
            RespostaChat.texto("desisto"),
        ])
        saida, escritas = self._sessao(cliente)
        self.assertEqual(escritas, [])
        respostas = [json.loads(m["content"]) for m in cliente.pedidos[1] if m["role"] == "tool"]
        self.assertTrue(all(not r["ok"] for r in respostas))
        recusas = [e for e in self.emissor.ler() if e["type"] == "tool_refused"]
        self.assertEqual(len(recusas), 2)
        self.assertFalse([n for n, _ in self.f.chamadas if n.startswith("escrever")])

    def test_argumentos_invalidos_viram_erro_para_o_modelo(self):
        resposta = RespostaChat.de_tool_calls([("ler_plano", {})])
        resposta.tool_calls[0]["argumentos"] = "{nao é json"
        cliente = ClienteChatFalso([resposta, RespostaChat.texto("ok")])
        saida, _ = self._sessao(cliente)
        erro = json.loads([m for m in cliente.pedidos[1] if m["role"] == "tool"][0]["content"])
        self.assertFalse(erro["ok"])
        self.assertEqual(saida.subtype, "success")

    def test_limite_de_turnos(self):
        cliente = ClienteChatFalso([RespostaChat.de_tool_calls([("ler_plano", {})]) for _ in range(5)])
        saida, _ = self._sessao(cliente, max_turnos=3)
        self.assertEqual(saida.subtype, "error_max_turns")
        self.assertEqual(len(cliente.pedidos), 3)

    def test_limite_de_orcamento(self):
        caro = (200_000, 10_000)  # 1,00 USD por turno
        cliente = ClienteChatFalso([RespostaChat.de_tool_calls([("ler_plano", {})], tokens=caro) for _ in range(5)])
        saida, _ = self._sessao(cliente, teto=1.5)
        self.assertEqual(saida.subtype, "error_max_budget_usd")
        self.assertEqual(len(cliente.pedidos), 2)

    def test_sem_usage_custo_desconhecido(self):
        resposta = RespostaChat.texto("fim")
        resposta.uso_informado = False
        saida, _ = self._sessao(ClienteChatFalso([resposta]))
        self.assertIsNone(saida.total_cost_usd)

    def test_erro_de_api_encerra_sem_perder_o_que_foi_feito(self):
        cliente = _ClienteQueFalha([RespostaChat.de_tool_calls(
            [("escrever_modelo", {"caminho": MODELO, "conteudo": "select 3"})])])
        saida, escritas = self._sessao(cliente)
        self.assertEqual(saida.subtype, "error_during_execution")
        self.assertEqual(escritas, [MODELO])
        self.assertGreater(saida.total_cost_usd, 0)


if __name__ == "__main__":
    unittest.main()
