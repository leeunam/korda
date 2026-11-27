"""Aprovação, custos e seleção dos executores do worker sem chamadas externas."""

import hashlib
import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from korda_execution import construcao
from korda_execution.documento_base import SECOES
from korda_execution.eventos import EmissorEventos
from korda_execution.harness.adaptador_eventos import exportar_execucao
from korda_execution.harness.cliente_chat import ClienteChatFalso, ClienteComOrcamento, ErroLLM, RespostaChat
from korda_execution.harness.config import ConfigHarness, ErroConfiguracao
from korda_execution.sandbox import ErroSandbox, LocalDockerSandbox

from .fakes import FerramentasFalsas


class TestConstrucaoWorker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        self.eventos = EmissorEventos(self.raiz / "eventos.jsonl", "run-harness")
        self.modelos = sorted(p.relative_to(construcao.PROJETO).as_posix() for p in (construcao.PROJETO / "models").glob("*.sql"))
        self.plano = {
            "construction": {"document": "\n".join("## " + t for t in SECOES), "model": "falso", "synthetic": True},
            "plan_version": "b" * 64, "context_id": "c", "context_revision": 2,
            "limits": {"max_repair_attempts_per_step": 3}, "editable_models": self.modelos,
            "rules": {"rateio_cte": {"value": "peso"}}, "metrics": {"otif": {"unit": "%"}},
            "tasks": [{"id": "ouro", "depends_on": [], "verify": "conferir indicadores"}],
            "gaps": [], "evidence": [], "source_profile": {}, "destination": "destino-privado",
        }
        self.ferramentas = FerramentasFalsas(dict.fromkeys(self.modelos, ""), self.modelos)
        self.verificar = Mock()
        (self.raiz / "fontes.json").write_text(json.dumps({"erp_pedidos": {"colunas": ["cd_ped"]}}))

    def construir(self, config, **kwargs):
        return construcao.construir_modelos(config, self.plano, self.ferramentas, self.eventos,
                                           self.raiz, self.verificar, **kwargs)

    def medicao(self):
        return json.loads((self.raiz / "medicao.json").read_text())

    def test_nenhum_executor_amplia_a_versao_legada(self):
        self.plano["editable_models"] = ["models/prata_ctes.sql"]
        with self.assertRaisesRegex(ErroConfiguracao, "nova versão"):
            construcao.preparar_construcao(self.plano)

    def test_escolha_de_chat_exige_gate_antes_da_sandbox(self):
        with patch.dict(os.environ, {"KORDA_EXECUTOR": "chat"}, clear=True), self.assertRaises(ErroConfiguracao):
            construcao.preparar_construcao(self.plano)

    def test_offline_constroi_todos_e_mede_a_mesma_versao(self):
        for modo in ("roteirizado", "falso"):
            with self.subTest(modo=modo), patch.object(construcao, "ClienteChatHttp", side_effect=AssertionError):
                config = ConfigHarness.de_ambiente({"KORDA_EXECUTOR": modo})
                cliente = None
                if modo == "falso":
                    chamadas = [("escrever_modelo", {"caminho": n, "conteudo": "select 1"}) for n in self.modelos]
                    cliente = ClienteChatFalso([RespostaChat.de_tool_calls(chamadas, tokens=(0, 0)),
                                                RespostaChat.texto("fim", tokens=(0, 0))])
                resultado = self.construir(config, cliente_llm=cliente)
                self.assertTrue(resultado["ok"], resultado)
                self.assertEqual(set(self.ferramentas.escritas()), set(self.modelos))
                medicao = self.medicao()
                self.assertEqual((medicao["executor"], medicao["plan_version"]), (modo, self.plano["plan_version"]))
                self.assertTrue(medicao["synthetic"])
                self.assertTrue(medicao["custo_completo"])
                self.assertEqual(medicao["custo_centavos"], 0)
                doc = (self.raiz / "documento_base.md").read_bytes()
                self.assertEqual(medicao["documento_base"]["sha256"], hashlib.sha256(doc).hexdigest())
                self.assertNotIn(b"destino-privado", doc)
                self.assertTrue(all(titulo.encode() in doc for titulo in SECOES))

    def test_sql_longo_valido_e_aceito_pelo_build_sem_transitar_no_chat(self):
        nome = self.modelos[0]
        sql = "-- " + "a" * 16_001 + "\nSELECT 42 AS resposta"
        referencia = dict.fromkeys(self.modelos, "select 1")
        referencia[nome] = sql

        def build(subcomando):
            self.assertEqual(subcomando, "build")
            db = sqlite3.connect(":memory:")
            try:
                self.assertEqual(db.execute(self.ferramentas.modelos[nome]).fetchone(), (42,))
            finally:
                db.close()
            return {"ok": True}

        with patch.object(construcao, "modelos_a_mao", return_value=referencia), \
             patch.object(self.ferramentas, "ler_arquivo", side_effect=AssertionError("releitura de SQL")), \
             patch.object(self.ferramentas, "rodar_dbt", side_effect=build):
            resultado = self.construir(ConfigHarness.de_ambiente({}))
        self.assertTrue(resultado["ok"], resultado)
        self.assertEqual(resultado["correcoes"], 0)

    def test_modelo_ausente_no_build_produz_diagnostico_corrigivel(self):
        nome = "models/prata_ctes.sql"
        def build(subcomando):
            self.assertEqual(subcomando, "build")
            if build_mock.call_count == 1:
                self.ferramentas.modelos[nome] = ""
                return {"ok": False, "stdout": "Compilation Error: model prata_ctes was not found"}
            self.assertTrue(self.ferramentas.modelos[nome].strip())
            return {"ok": True}

        with patch.object(self.ferramentas, "rodar_dbt", side_effect=build) as build_mock:
            resultado = self.construir(ConfigHarness.de_ambiente({}))
        self.assertTrue(resultado["ok"], resultado)
        self.assertEqual(resultado["correcoes"], 1)

    def test_teste_protegido_de_dados_interrompe_sem_reparo(self):
        self.ferramentas.resultados_dbt = [{"ok": False, "stdout": "Failure in test integridade_fontes"}]
        resultado = self.construir(ConfigHarness.de_ambiente({}))
        self.assertFalse(resultado["ok"])
        self.assertEqual(resultado["codigo"], "dados")
        self.assertEqual(resultado["correcoes"], 0)

    def test_construtor_revogado_registra_gasto_e_nao_escreve(self):
        self.verificar.side_effect = ValueError("revogada")
        with self.assertRaisesRegex(ValueError, "revogada"):
            self.construir(ConfigHarness.de_ambiente({}))
        self.assertFalse(self.ferramentas.escritas())
        self.assertEqual(self.medicao()["custo_usd"], 0)

    def test_chat_usa_exatamente_documento_aprovado_repara_e_reexporta(self):
        config = ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "chat", "KORDA_PERMITIR_LLM_REAL": "1",
                                           "KORDA_LLM_CHAVE": "chave-sintetica"})
        chamadas = [("escrever_modelo", {"caminho": n, "conteudo": "select 1"}) for n in self.modelos]
        cliente = ClienteChatFalso([RespostaChat.de_tool_calls(chamadas), RespostaChat.texto("fim"),
                                    RespostaChat.de_tool_calls(chamadas[:1]), RespostaChat.texto("corrigido")])
        exportar = Mock(side_effect=[Mock(ok=False, codigo=1, estourou_tempo=False, stderr="contrato incompleto"),
                                     Mock(ok=True)])
        with patch.object(construcao, "modelos_a_mao", side_effect=AssertionError("vazamento da solução")):
            resultado = self.construir(config, cliente_llm=cliente, exportar=exportar)
        self.assertTrue(resultado["ok"], resultado)
        self.assertEqual(exportar.call_count, 2)
        self.assertEqual(resultado["correcoes"], 1)
        self.assertEqual(len(cliente.pedidos), 4)
        for indice in (0, 2):
            self.assertIn(self.plano["construction"]["document"], cliente.pedidos[indice][1]["content"])
        self.assertIn("contrato incompleto", cliente.pedidos[2][1]["content"])
        self.assertEqual((self.raiz / "documento_base.md").read_text(), self.plano["construction"]["document"])
        medicao = self.medicao()
        self.assertEqual((medicao["tokens_entrada"], medicao["tokens_saida"]), (2200, 440))
        self.assertEqual(medicao["documento_base"]["origem"], "construction")
        pro_front = exportar_execucao(self.eventos.caminho, synthetic=False)["custo"]
        self.assertEqual(pro_front["custo_total_centavos"], medicao["custo_centavos"])
        self.assertEqual(pro_front["orcamento_centavos"], 4800)
        self.assertNotIn(config.chave_api, json.dumps(medicao))
        self.assertNotIn("destino-privado", str(cliente.pedidos))

    def test_custo_desconhecido_impede_uma_segunda_chamada(self):
        transporte = Mock()
        resposta = RespostaChat.texto("fim")
        resposta.uso_informado = False
        transporte.completar.return_value = resposta
        cliente = ClienteComOrcamento(transporte, 0.05, (4, 20), self.verificar)
        cliente.completar([], [])
        with self.assertRaises(ErroLLM):
            cliente.completar([], [])
        self.assertEqual(transporte.completar.call_count, 1)
        with self.assertRaises(ErroLLM):
            ClienteComOrcamento(transporte, .00001, (4, 20), self.verificar).completar([], [])
        self.assertEqual(transporte.completar.call_count, 1)

    def test_chat_reserva_saldo_das_proximas_etapas_antes_do_envio(self):
        transporte = Mock()
        transporte.completar.return_value = RespostaChat.texto("ok", (10, 10))
        cliente = ClienteComOrcamento(transporte, 1.00, (4, 20), self.verificar)
        cliente.limitar_sessao(0.02)
        cliente.completar([], [])
        teto = transporte.completar.call_args.kwargs["max_tokens"]
        self.assertGreater(teto, 0)
        self.assertLess(teto, 1000)
        cliente.limitar_sessao(.35)
        cliente.completar([], [])
        self.assertGreater(transporte.completar.call_args.kwargs["max_tokens"], teto)

    def test_uso_ausente_escala_sem_chamadas_adicionais(self):
        resposta = RespostaChat.de_tool_calls([("escrever_modelo", {"caminho": self.modelos[0], "conteudo": "select 1"})])
        resposta.uso_informado = False
        cliente = ClienteChatFalso([resposta])
        resultado = self.construir(ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "falso"}), cliente_llm=cliente)
        self.assertEqual(resultado["codigo"], "orcamento_llm")
        self.assertEqual(len(cliente.pedidos), 1)
        self.assertFalse(self.medicao()["custo_completo"])
        self.assertFalse(self.ferramentas.escritas())

    def test_revogacao_entre_ferramentas_da_mesma_resposta(self):
        chamadas = [("escrever_modelo", {"caminho": n, "conteudo": "select 1"}) for n in self.modelos]
        cliente = ClienteChatFalso([RespostaChat.de_tool_calls(chamadas)])

        def verificar():
            if self.ferramentas.escritas():
                raise ValueError("execução revogada")

        self.verificar.side_effect = verificar
        with self.assertRaisesRegex(ValueError, "revogada"):
            self.construir(ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "falso"}), cliente_llm=cliente)
        self.assertEqual(self.ferramentas.escritas(), [self.modelos[0]])
        self.assertEqual(self.medicao()["tokens_entrada"], 1000)
        self.assertEqual(len(cliente.pedidos), 1)

    def test_falso_e_chat_requerem_documento_aprovado(self):
        self.plano.pop("construction")
        for env in ({"KORDA_EXECUTOR": "falso"}, {"KORDA_EXECUTOR": "chat", "KORDA_PERMITIR_LLM_REAL": "1",
                                                  "KORDA_LLM_CHAVE": "teste"}):
            cliente = ClienteChatFalso([])
            with self.subTest(env=env), self.assertRaisesRegex(ErroConfiguracao, "planejar"):
                self.construir(ConfigHarness.de_ambiente(env), cliente_llm=cliente)
            self.assertFalse(cliente.pedidos)

    def test_aceita_o_glob_aprovado_da_main_no_plano_historico(self):
        self.plano.update(schema_version="0.1.0", editable_models=["models/*"])
        cfg = ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "falso"})
        self.assertIs(construcao.preparar_construcao(self.plano, cfg, cliente_llm=ClienteChatFalso([])), cfg)
        self.plano["schema_version"] = "0.2.0"
        with self.assertRaises(ErroConfiguracao):
            construcao.preparar_construcao(self.plano, cfg, cliente_llm=ClienteChatFalso([]))

    def test_sdk_fica_reservado_para_uso_avulso(self):
        cfg = ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "agente_sdk", "KORDA_PERMITIR_LLM_REAL": "1",
                                         "ANTHROPIC_API_KEY": "chave-sintetica"})
        with self.assertRaisesRegex(ErroConfiguracao, "Feita"):
            self.construir(cfg)

    def test_exportacao_com_falha_tecnica_nao_dispara_correcao(self):
        exportar = Mock(return_value=Mock(ok=False, codigo=137, estourou_tempo=True, stderr="timeout"))
        resultado = self.construir(ConfigHarness.de_ambiente({}), exportar=exportar)
        self.assertEqual(resultado["codigo"], "tecnico")
        self.assertEqual(resultado["correcoes"], 0)
        exportar.assert_called_once()

    def test_modelos_da_referencia_nao_entram_na_sandbox_vazia(self):
        fonte = self.raiz / "fonte"
        fonte.mkdir()
        (fonte / "manifesto.json").write_text("{}")
        origem = self.raiz / "projeto"
        (origem / "models").mkdir(parents=True)
        (origem / "models/um.sql").write_text("select 'solucao'")
        (origem / "models/outro.sql").write_text("select 'somente no host'")
        (origem / "dbt_project.yml").write_text("name: teste")
        (origem / "target").mkdir()
        (origem / "target/manifest.json").write_text("sql compilado")
        with self.assertRaises(ErroSandbox):
            LocalDockerSandbox("invalida", origem, fonte, modelos_vazios=True)
        sandbox = LocalDockerSandbox("valida", origem, fonte, raiz_runs=self.raiz / "runs",
                                     modelos_vazios=True, modelos_permitidos=("models/um.sql",))
        cid = "a" * 64
        with patch("korda_execution.sandbox.imagem_existe", return_value=True), \
             patch("korda_execution.sandbox.os.getuid", return_value=1000), \
             patch("korda_execution.sandbox.subprocess.run",
                   return_value=subprocess.CompletedProcess([], 0, stdout=cid, stderr="")) as docker:
            sandbox.criar()
            try:
                argv = docker.call_args.args[0]
                pasta = sandbox.dir_run / "projeto"
                self.assertEqual((pasta / "models/um.sql").read_bytes(), b"")
                self.assertFalse((pasta / "models/outro.sql").exists())
                self.assertFalse((pasta / "target").exists())
                self.assertIn(f"type=bind,src={pasta / 'models/um.sql'},dst=/work/projeto/models/um.sql", argv)
                self.assertNotIn(f"type=bind,src={pasta / 'models'},dst=/work/projeto/models", argv)
            finally:
                sandbox.destruir()


if __name__ == "__main__":
    unittest.main()
