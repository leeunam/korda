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
from korda_execution.harness.cliente_chat import ClienteComOrcamento, ErroLLM, RespostaChat
from korda_execution.harness.config import ConfigHarness, ErroConfiguracao
from korda_execution.harness.tipos import SaidaSessao
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
            "plan_version": "b" * 64, "context_id": "c", "context_revision": 2,
            "limits": {"max_repair_attempts_per_step": 3}, "editable_models": self.modelos,
            "rules": {"rateio_cte": {"value": "peso"}}, "metrics": {"otif": {"unit": "%"}},
            "tasks": [{"id": "ouro", "depends_on": [], "verify": "conferir indicadores"}],
            "gaps": [], "evidence": [], "source_profile": {}, "destination": "destino-privado",
        }
        self.ferramentas = FerramentasFalsas(dict.fromkeys(self.modelos, ""), self.modelos)
        self.verificar = Mock()
        (self.raiz / "fontes.json").write_text(json.dumps({"erp_pedidos": {"colunas": ["cd_ped"]}}))

    def construir(self, config):
        return construcao.construir_modelos(config, self.plano, self.ferramentas, self.eventos,
                                           self.raiz, self.verificar)

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
                resultado = self.construir(config)
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

        with patch.object(construcao, "_referencia", return_value=referencia), \
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

    def test_chat_com_transporte_falso_mede_documento_e_pipeline(self):
        config = ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "chat", "KORDA_PERMITIR_LLM_REAL": "1",
                                           "KORDA_LLM_CHAVE": "chave-sintetica"})
        resposta_documento = RespostaChat.texto("\n".join("## " + titulo for titulo in SECOES))
        respostas = [resposta_documento, RespostaChat.de_tool_calls(
            [("escrever_modelo", {"caminho": n, "conteudo": "select 1"}) for n in self.modelos]), RespostaChat.texto("fim")]
        transporte = Mock()
        transporte.completar.side_effect = respostas
        with patch.object(construcao, "ClienteChatHttp", return_value=transporte):
            resultado = self.construir(config)
        self.assertTrue(resultado["ok"], resultado)
        self.assertEqual(transporte.completar.call_count, 3)
        self.assertEqual(transporte.completar.call_args_list[0].args[1], [])
        for chamada in transporte.completar.call_args_list:
            self.assertGreater(chamada.kwargs["max_tokens"], 0)
        medicao = self.medicao()
        self.assertFalse(medicao["synthetic"])
        self.assertEqual(medicao["tokens_entrada"], 1200)
        self.assertEqual(medicao["tokens_saida"], 240)
        self.assertEqual(medicao["documento_base"]["tokens_entrada"], 100)
        pro_front = exportar_execucao(self.eventos.caminho, synthetic=False)["custo"]
        self.assertEqual(pro_front["custo_total_centavos"], medicao["custo_centavos"])
        self.assertEqual(pro_front["orcamento_centavos"], 4800)
        agente = next(e for e in self.eventos.ler() if e["type"] == "agent_finished")
        self.assertEqual(agente["dados"]["custo_total_centavos"], medicao["custo_centavos"])
        self.assertNotIn(config.chave_api, json.dumps(medicao))
        self.assertNotIn("destino-privado", str(transporte.completar.call_args_list))

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

    def test_documento_sem_uso_interrompe_antes_da_construcao(self):
        config = ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "chat", "KORDA_PERMITIR_LLM_REAL": "1",
                                            "KORDA_LLM_CHAVE": "chave-sintetica"})
        resposta = RespostaChat.texto("\n".join("## " + titulo for titulo in SECOES))
        resposta.uso_informado = False
        with patch.object(construcao, "ClienteChatHttp") as fabrica:
            fabrica.return_value.completar.return_value = resposta
            with self.assertRaisesRegex(ValueError, "uso do documento-base"):
                self.construir(config)
        self.assertEqual(fabrica.return_value.completar.call_count, 1)
        self.assertFalse(self.medicao()["custo_completo"])
        self.assertFalse(self.ferramentas.escritas())

    def test_documento_vazio_registra_tokens_efetivamente_cobrados(self):
        config = ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "chat", "KORDA_PERMITIR_LLM_REAL": "1",
                                            "KORDA_LLM_CHAVE": "chave-sintetica"})
        with patch.object(construcao, "ClienteChatHttp") as fabrica:
            fabrica.return_value.completar.return_value = RespostaChat.texto("", tokens=(160, 4))
            with self.assertRaisesRegex(ValueError, "documento-base vazio"):
                self.construir(config)
        self.assertTrue(self.medicao()["custo_completo"])
        self.assertEqual(self.medicao()["tokens_entrada"], 160)
        self.assertGreater(self.medicao()["custo_usd"], 0)
        self.assertFalse(self.ferramentas.escritas())

    def test_sdk_somente_corrige_modelos_ja_construidos(self):
        config = ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "agente_sdk", "KORDA_PERMITIR_LLM_REAL": "1",
                                            "ANTHROPIC_API_KEY": "chave-sintetica"})
        self.ferramentas.resultados_dbt = [{"ok": False, "stdout": "Failure in test contrato_exportacao"}]
        with patch.object(construcao, "CorretorAgente") as sdk, patch.object(construcao, "ClienteChatHttp") as http:
            sdk.return_value.return_value = {"ok": True, "custo_centavos": 0}
            resultado = self.construir(config)
        self.assertTrue(resultado["ok"], resultado)
        self.assertEqual(resultado["correcoes"], 1)
        sdk.return_value.assert_called_once()
        http.assert_not_called()
        self.assertEqual(self.medicao()["construtor"], "roteirizado")
        self.assertEqual(self.medicao()["executor"], "agente_sdk")

    def test_sdk_estouro_de_orcamento_recusa_apesar_da_escrita_e_registra_gasto(self):
        config = ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "agente_sdk", "KORDA_PERMITIR_LLM_REAL": "1",
                                            "ANTHROPIC_API_KEY": "chave-sintetica", "KORDA_ORCAMENTO_EXECUCAO_USD": "0.10"})
        for subtipo, custo in [("error_max_budget_usd", 0.01), ("success", 0.12)]:
            with self.subTest(subtipo=subtipo):
                self.ferramentas.resultados_dbt = [{"ok": False, "stdout": "Compilation Error in model ouro_kpis"}]

                def sessao(prompt, ctx):
                    modelo = "models/ouro_kpis.sql"
                    if ctx.ferramentas.escrever_modelo(modelo, "select 1")["ok"]:
                        ctx.escritas.append(modelo)
                    return SaidaSessao(subtipo, 1, custo, {}, [])

                with patch("korda_execution.harness.agente_sdk.rodar_sessao_sdk", side_effect=sessao) as chamada:
                    resultado = self.construir(config)
                self.assertFalse(resultado["ok"])
                self.assertEqual(resultado["codigo"], "correcao_recusada")
                self.assertIn("orçamento", resultado["erro"])
                chamada.assert_called_once()
                self.assertTrue(self.medicao()["custo_completo"])
                self.assertEqual(self.medicao()["custo_usd"], custo)

    def test_falha_de_transporte_do_sdk_preserva_custo_desconhecido(self):
        config = ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "agente_sdk", "KORDA_PERMITIR_LLM_REAL": "1",
                                            "ANTHROPIC_API_KEY": "chave-sintetica"})
        self.ferramentas.resultados_dbt = [{"ok": False, "stdout": "Compilation Error in model ouro_kpis"}]
        with patch.object(construcao, "CorretorAgente") as sdk:
            sdk.return_value.side_effect = RuntimeError("sessão do SDK interrompida")
            resultado = self.construir(config)
        self.assertEqual(resultado["codigo"], "correcao_interrompida")
        self.assertFalse(self.medicao()["custo_completo"])

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
