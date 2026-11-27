"""Ponte da entrevista usando SQLite real, transporte HTTP em memória e executor sintético."""
import copy
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services.planning.tests.test_ponte_contexto import entrevista_completa
from korda_execution.aprovacoes import ErroAprovacao
from korda_execution.artefatos import manifesto_revisao
from korda_execution.operador import ErroOperador, FonteEntrevista, Operador
from korda_execution.operador_http import Handler


class SocketMemoria:
    def __init__(self, pedido):
        self.entrada = io.BytesIO(pedido)
        self.saida = bytearray()

    def makefile(self, *args):
        return self.entrada

    def sendall(self, dados):
        self.saida.extend(dados)

    def settimeout(self, timeout):
        pass


class TestOperadorHTTP(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.raiz = Path(temp.name)
        self.doc = entrevista_completa()
        self.projeto = self.doc["project_id"] = "entrevista-01"
        self.exports = self.raiz / "exports"
        (self.exports / self.projeto).mkdir(parents=True)
        self.gravar(self.doc)
        self.chamadas = 0
        self.abrir = threading.Event()
        self.abrir.set()
        self.falhar = False
        self.fonte = FonteEntrevista(exports=self.exports)
        self.op = Operador(self.projeto, raiz=self.raiz / "runs", fontes=self.raiz / "fontes",
                           fonte=self.fonte, executar_run=self.executar)
        self.addCleanup(self.op.fechar)
        self.addCleanup(self.abrir.set)

    def gravar(self, doc):
        path = self.exports / self.projeto / f"{doc['revision']}.json"
        path.write_text(json.dumps(doc))
        return path

    def executar(self, registro, plano, run_id, *, raiz, fontes, cfg):
        registro.iniciar(plano["project_id"], plano["plan_version"], run_id)
        self.chamadas += 1
        assert cfg.executor == "roteirizado" and not cfg.permitir_llm_real and not cfg.chave_api
        if self.falhar or not self.abrir.wait(timeout=3):
            raise RuntimeError("falha no executor de teste")
        pasta = raiz / "revisao" / run_id
        saida = pasta / "resultados"
        saida.mkdir(parents=True)
        (saida / "kpis.json").write_text(json.dumps({"kpis": {"custo_frete_por_entrega": 10, "otif_pct": 45, "ocupacao_pct": 60}}))
        (saida / "pacote.zip").write_bytes(b"pacote revisado")
        for nome in ("por_pedido.csv", "por_viagem.csv"):
            (saida / nome).write_text("id,valor\n1,45\n")
        (pasta / "avaliacao.json").write_text('{"aprovado":true,"classe":"aprovado","divergencias":0,"comparados":{"kpis":3}}')
        registro.finalizar(run_id, aprovado=True, manifesto=manifesto_revisao(saida))

    def importar(self):
        atual = self.op.fonte_atual()
        return self.op.acao("importar", {"revision": atual["revision"], "context_sha256": atual["sha256"]})

    def aprovar(self):
        versao = self.importar()["plan"]["plan_version"]
        self.op.acao("decidir-plano", {"plan_version": versao, "pessoa": "Revisora", "aprovar": True})
        return {"plan_version": versao}

    def aguardar(self):
        self.op.pool.submit(lambda: None).result(timeout=8)

    def test_execucao_idempotente_gates_reais_download_integro(self):
        v = {"plan_version": self.importar()["plan"]["plan_version"]}
        with self.assertRaises(ErroOperador):
            self.op.acao("executar", v)
        self.assertEqual(self.aprovar(), v)
        self.abrir.clear()
        run = self.op.acao("executar", v)["run"]["run_id"]
        self.assertEqual(self.op.acao("executar", v)["run"]["run_id"], run)
        self.abrir.set()
        self.aguardar()
        self.assertEqual(self.chamadas, 1)
        resultado = self.op.estado()["run"]
        self.assertEqual(resultado["state"], "aguardando_aprovacao_entrega")
        self.assertEqual(resultado["kpis"]["otif_pct"], 45)
        self.assertTrue(resultado["avaliacao"]["aprovado"])
        self.assertEqual(resultado["arquivos"], [])
        v = {**v, "run_id": run}
        with self.assertRaises(ErroAprovacao):
            self.op.acao("promover", v)
        with self.assertRaises(ErroOperador):
            self.op.baixar(run, "kpis.json")
        self.op.acao("decidir-entrega", {**v, "pessoa": "Revisor 2", "aprovar": True})
        entrega = self.op.acao("promover", v)["run"]
        self.assertEqual(entrega["state"], "promovida")
        self.assertEqual(self.op.acao("promover", v)["run"], entrega)
        self.assertIn("pacote.zip", entrega["arquivos"])
        self.assertEqual(self.op.baixar(run, "pacote.zip"), b"pacote revisado")
        publicado = self.op.raiz / "entregas" / "painel-demo" / run / "pacote.zip"
        publicado.write_bytes(b"alterado")
        with self.assertRaises(ErroOperador):
            self.op.baixar(run, "pacote.zip")

    def test_pendencia_de_implementacao_preserva_regra_e_invalida_run(self):
        v = self.aprovar()
        run = self.op.acao("executar", v)["run"]["run_id"]
        self.aguardar()
        nova = copy.deepcopy(self.doc)
        nova["revision"] += 1
        nova["claims"][0]["value"] = "volume"
        self.gravar(nova)
        estado = self.importar()
        self.assertIsNone(estado["plan"])
        self.assertEqual(estado["source"]["estado"], "pendente")
        self.assertEqual(estado["source"]["regras"]["rateio_cte"]["value"], "volume")
        self.assertIn("Implementação", estado["source"]["pendencias"][0]["pergunta"])
        self.assertEqual(self.op.registro.consultar(run)["state"], "invalidada")
        with self.assertRaises(ErroOperador):
            self.op.acao("executar", v)
        anterior = self.op.fonte_atual(nova["revision"] - 1)
        with self.assertRaises(ErroOperador):
            self.op.importar(anterior["revision"], anterior["sha256"])

    def test_repetir_requer_id_de_falha_e_nao_roda_duas_vezes(self):
        v = self.aprovar()
        self.falhar = True
        run = self.op.acao("executar", v)["run"]["run_id"]
        self.aguardar()
        self.assertEqual(self.op.acao("executar", v)["run"]["state"], "falhou")
        self.assertEqual(self.chamadas, 1)
        self.falhar = False
        retry = {**v, "retry_run_id": run}
        novo = self.op.acao("executar", retry)["run"]["run_id"]
        self.assertNotEqual(novo, run)
        self.assertEqual(self.op.acao("executar", retry)["run"]["run_id"], novo)
        self.aguardar()
        self.assertEqual(self.chamadas, 2)

    def test_fonte_rejeita_mudanca_da_revisao_e_identidade_divergente(self):
        p = self.op.fonte_atual()
        with self.assertRaises(ErroOperador):
            self.op.importar(p["revision"], "0" * 64)
        self.importar()
        self.doc["created_at"] = "2026-11-28T10:00:00Z"
        self.gravar(self.doc)
        with self.assertRaises(ErroOperador):
            self.importar()
        for chave, valor in (("project_id", "outro"), ("synthetic", False), ("schema_version", "0.1.0")):
            self.gravar({**self.doc, chave: valor})
            with self.assertRaises(ErroOperador):
                self.op.fonte_atual()

    def http(self, metodo, caminho, *, corpo=b"", autenticado=True):
        cab = b"Authorization: Bearer token\r\n" if autenticado else b""
        req = (f"{metodo} /v1/projetos/{self.projeto}{caminho} HTTP/1.0\r\n".encode() + cab +
               f"Content-Length: {len(corpo)}\r\nContent-Type: application/json\r\n\r\n".encode() + corpo)
        sock = SocketMemoria(req)
        Handler(sock, ("127.0.0.1", 1), SimpleNamespace(operador=self.op, token=b"token"))
        headers, resultado = bytes(sock.saida).split(b"\r\n\r\n")
        return int(headers.split()[1]), json.loads(resultado)

    def test_transporte_autenticacao_revisao_e_corpo(self):
        self.assertEqual(self.http("GET", "", autenticado=False)[0], 401)
        self.assertEqual(self.http("GET", "")[1]["project_id"], self.projeto)
        status, fonte = self.http("GET", "/fonte?revision=2")
        self.assertEqual((status, fonte["estado"]), (200, "pronto"))
        self.assertEqual(self.http("GET", "/fonte?revision=")[0], 400)
        self.assertEqual(self.http("POST", "/importar", corpo=b'{"revision":2,"revision":2}')[0], 400)
        self.assertEqual(self.http("POST", "/importar", corpo=b'{' + b'x' * 18000)[0], 413)
        status, plano = self.http("POST", "/importar", corpo=json.dumps({"context_sha256": fonte["sha256"], "revision": 2}).encode())
        self.assertEqual((status, plano["plan"]["state"]), (200, "aguardando_aprovacao"))
        self.assertEqual(self.http("POST", "/executar", corpo=b'{"plan_version":"outro","fontes":"/tmp"}')[0], 400)
        self.assertEqual(self.http("GET", "/runs/ab/arquivos/registro.sqlite3")[0], 404)

    def test_exportacao_http_consulta_revisao_concreta_sem_redirecionar(self):
        fonte = FonteEntrevista(url="http://localhost:8000", token="apenas-leitura")
        resp = io.BytesIO(json.dumps(self.doc).encode())
        with patch("korda_execution.operador.build_opener") as criar:
            criar.return_value.open.return_value = resp
            self.assertEqual(fonte.ler(self.projeto, 2), self.doc)
            req = criar.return_value.open.call_args.args[0]
            self.assertEqual(req.full_url, "http://localhost:8000/v1/projects/entrevista-01/context/revisions/2/export")
            self.assertEqual(req.get_header("Authorization"), "Bearer apenas-leitura")
        with self.assertRaises(ValueError):
            FonteEntrevista(url="http://example.org", token="apenas-leitura")
