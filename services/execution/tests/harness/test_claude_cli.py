"""Executor claude_cli (login do plano, sem chave): nenhum teste aqui abre o CLI real nem chama o LLM.

O CLI é sempre falso: um script `claude` num PATH temporário, uma sessão injetada ou um `query` do SDK
substituído por mensagens roteirizadas.
"""

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from korda_execution import construcao, planejamento
from korda_execution.documento_base import SECOES, SISTEMA_DOCUMENTO
from korda_execution.eventos import EmissorEventos
from korda_execution.harness import agente_sdk
from korda_execution.harness.agente_sdk import (ARGS_ASSINATURA, CODIGO_LANCADOR_RECUSOU, ClienteClaudeCli,
                                                ContextoSessao, ErroSegurancaHarness, ExecutorClaudeCli,
                                                ambiente_minimo, escrever_lancador, verificar_init, verificar_login)
from korda_execution.harness.config import VARIAVEIS_PROIBIDAS_CLI, ConfigHarness, ErroConfiguracao
from korda_execution.harness.contexto import SISTEMA, SISTEMA_CONSTRUCAO, projetar_plano
from korda_execution.harness.ferramentas_agente import despachar
from korda_execution.harness.medicao import Medidor
from korda_execution.harness.politica import FERRAMENTAS, PREFIXO
from korda_execution.harness.tipos import SaidaSessao
from korda_execution.worker import FalhaExecucao

from ..test_planejamento import CONTEXTO, _decisao
from .fakes import FerramentasFalsas

SDK_INSTALADO = importlib.util.find_spec("claude_agent_sdk") is not None
MODELOS = ["models/prata_ctes.sql", "models/ouro_kpis.sql"]
PLANO = {"plan_version": "c" * 64, "editable_models": MODELOS, "limits": {"max_repair_attempts_per_step": 3},
         "rules": {"deduplicar_cte": True}, "metrics": {"custo_frete_por_entrega": {"acceptance": ["única"]}},
         "tasks": [{"id": "prata", "depends_on": [], "output": "ctes", "verify": "única"}]}
FALHA = {"ok": False, "codigo": "implementacao", "erro": "Failure in test chave_fiscal_unica"}
KORDA = sorted(PREFIXO + n for n in FERRAMENTAS)
STATUS_OK = {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty", "email": "alguem@exemplo.invalid",
             "orgName": "Org", "subscriptionType": "pro"}
LOGIN_OK = {"authMethod": "claude.ai", "subscriptionType": "pro"}


def _cfg(**extra):
    return ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "claude_cli", "KORDA_PERMITIR_LLM_REAL": "1",
                                      "KORDA_ORCAMENTO_EXECUCAO_USD": "3.00", **extra})


class SessaoFalsa:
    """Cada item diz custo, subtype, modelos escritos e se a cota acabou."""

    def __init__(self, sessoes):
        self.sessoes = list(sessoes)
        self.chamadas: list[tuple[str, ContextoSessao]] = []

    def __call__(self, prompt, ctx):
        self.chamadas.append((prompt, ctx))
        s = self.sessoes.pop(0)
        if isinstance(s, Exception):
            raise s
        for caminho in s.get("escreve", []):
            asyncio.run(despachar("escrever_modelo", {"caminho": caminho, "conteudo": "select 1"},
                                  ctx.ferramentas, ctx.escritas))
        return SaidaSessao(subtype=s.get("subtype", "success"), num_turns=s.get("turnos", 5),
                           total_cost_usd=s.get("custo", 0.2),
                           usage={"input_tokens": 100, "cache_creation_input_tokens": 400,
                                  "cache_read_input_tokens": 500, "output_tokens": 50},
                           ferramentas_sessao=KORDA, erro=s.get("erro"), limite_uso=s.get("limite", False),
                           texto=s.get("texto", ""), modelo="claude-sonnet-5-5", tokens_por_turno=[[1000, 50]])


class TestPortoes(unittest.TestCase):
    def test_exige_autorizacao_explicita(self):
        with self.assertRaisesRegex(ErroConfiguracao, "cota do plano"):
            ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "claude_cli"})

    def test_recusa_qualquer_credencial_de_api_mesmo_vazia(self):
        for nome in VARIAVEIS_PROIBIDAS_CLI:
            for valor in ("sk-x", ""):
                with self.subTest(nome=nome, valor=valor), self.assertRaisesRegex(ErroConfiguracao, nome):
                    _cfg(**{nome: valor})

    def test_liberado_sem_chave_com_sonnet_e_cobranca_por_assinatura(self):
        cfg = _cfg()
        self.assertIsNone(cfg.chave_api)
        self.assertEqual((cfg.modelo, cfg.cobranca), ("sonnet", "assinatura"))
        self.assertTrue(cfg.usa_llm)
        self.assertEqual(_cfg(KORDA_MODELO="opus").modelo, "opus")

    def test_chat_da_feita_continua_igual(self):
        cfg = ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "chat", "KORDA_PERMITIR_LLM_REAL": "1",
                                         "KORDA_LLM_CHAVE": "fk-teste"})
        self.assertEqual((cfg.chave_api, cfg.cobranca), ("fk-teste", "api"))
        with self.assertRaises(ErroConfiguracao):
            ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "chat", "KORDA_PERMITIR_LLM_REAL": "1"})

    def test_executores_recusam_config_sem_portao(self):
        falso = ConfigHarness.de_ambiente({"KORDA_EXECUTOR": "falso"})
        with self.assertRaises(ValueError):
            ExecutorClaudeCli(falso, FerramentasFalsas({}, MODELOS), projetar_plano(PLANO), {}, 3, None, None)
        with self.assertRaises(ValueError):
            ClienteClaudeCli(falso)


class TestAmbienteMinimo(unittest.TestCase):
    ORIGEM = {"KORDA_LLM_CHAVE": "fk-segredo", "SEGREDO_X": "y", "PATH": "/caminho/estranho", "HOME": "/outra",
              "CLAUDE_CODE_ENTRYPOINT": "sdk-py", "CLAUDE_AGENT_SDK_VERSION": "0.2.180", "USER": "gabriel",
              "AWS_SECRET_ACCESS_KEY": "z"}

    def test_so_variaveis_permitidas(self):
        amb = ambiente_minimo("/opt/claude/bin/claude", self.ORIGEM, home="/home/teste")
        self.assertEqual(amb["HOME"], "/home/teste")
        self.assertEqual(amb["PATH"].split(os.pathsep)[0], "/opt/claude/bin")
        self.assertNotIn("/caminho/estranho", amb["PATH"])
        self.assertEqual(amb["CLAUDE_CODE_ENTRYPOINT"], "sdk-py")
        for nome in ("KORDA_LLM_CHAVE", "SEGREDO_X", "AWS_SECRET_ACCESS_KEY", *VARIAVEIS_PROIBIDAS_CLI):
            self.assertNotIn(nome, amb)
        self.assertNotIn("fk-segredo", json.dumps(amb))

    def _cli_falso(self, pasta: Path) -> tuple[Path, Path]:
        saida = pasta / "visto.json"
        claude = pasta / "claude"
        claude.write_text(f"#!{sys.executable}\nimport json, os, sys\n"
                          f"open({str(saida)!r}, 'w').write(json.dumps({{'env': dict(os.environ), 'argv': sys.argv[1:]}}))\n")
        claude.chmod(0o700)
        return claude, saida

    def test_lancador_troca_o_ambiente_herdado_do_sdk(self):
        with tempfile.TemporaryDirectory() as tmp:
            claude, saida = self._cli_falso(Path(tmp))
            lancador = escrever_lancador(Path(tmp), str(claude), home=tmp)
            herdado = {**os.environ, **{k: v for k, v in self.ORIGEM.items() if k != "PATH"}}
            for nome in VARIAVEIS_PROIBIDAS_CLI:
                herdado.pop(nome, None)
            r = subprocess.run([str(lancador), "--print", "-v"], env=herdado, capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            visto = json.loads(saida.read_text())
        self.assertEqual(visto["argv"], ["--print", "-v"])
        permitidas = {"HOME", "PATH", "USER", *agente_sdk.VARIAVEIS_FIXAS, *agente_sdk.VARIAVEIS_DO_SDK}
        self.assertLessEqual(set(visto["env"]) - {"PWD"}, permitidas)
        self.assertEqual(visto["env"]["HOME"], tmp)
        self.assertEqual(visto["env"]["CLAUDE_AGENT_SDK_VERSION"], "0.2.180")
        self.assertNotIn("KORDA_LLM_CHAVE", visto["env"])
        self.assertNotIn("SEGREDO_X", visto["env"])

    def test_lancador_aborta_com_credencial_de_api_sem_executar_o_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            claude, saida = self._cli_falso(Path(tmp))
            lancador = escrever_lancador(Path(tmp), str(claude), home=tmp)
            r = subprocess.run([str(lancador)], env={**os.environ, "ANTHROPIC_API_KEY": ""}, capture_output=True,
                               text=True, timeout=30)
            self.assertEqual(r.returncode, CODIGO_LANCADOR_RECUSOU)
            self.assertIn("ANTHROPIC_API_KEY", r.stderr)
            self.assertFalse(saida.exists())


class TestLogin(unittest.TestCase):
    def _rodar(self, status=STATUS_OK, codigo=0, saida=None):
        def rodar(cmd, **kw):
            self.cmd, self.kw = cmd, kw
            return subprocess.CompletedProcess(cmd, codigo, saida if saida is not None else json.dumps(status), "")
        return rodar

    def test_login_do_plano_devolve_so_metodo_e_plano(self):
        with patch.dict(os.environ, {"KORDA_LLM_CHAVE": "fk-segredo"}):
            info = verificar_login(self._rodar(), claude_real="/x/claude")
        self.assertEqual(info, LOGIN_OK)
        self.assertEqual(self.cmd, ["/x/claude", "auth", "status", "--json"])
        self.assertNotIn("KORDA_LLM_CHAVE", self.kw["env"])

    def test_recusa_sem_login_ou_por_outra_via(self):
        casos = {"deslogado": dict(STATUS_OK, loggedIn=False), "bedrock": dict(STATUS_OK, apiProvider="bedrock"),
                 "chave": dict(STATUS_OK, authMethod="api_key")}
        for nome, status in casos.items():
            with self.subTest(nome), self.assertRaisesRegex(ErroConfiguracao, "/login"):
                verificar_login(self._rodar(status), claude_real="/x/claude")

    def test_subcomando_ausente_ou_falhando_pede_login(self):
        for codigo, saida in ((1, ""), (0, "unknown command"), (2, "{}")):
            with self.subTest(codigo=codigo), self.assertRaisesRegex(ErroConfiguracao, "/login"):
                verificar_login(self._rodar(codigo=codigo, saida=saida), claude_real="/x/claude")

        def quebra(*a, **k):
            raise OSError("sem binário")
        with self.assertRaisesRegex(ErroConfiguracao, "/login"):
            verificar_login(quebra, claude_real="/x/claude")

    def test_cli_falso_no_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            claude = Path(tmp) / "claude"
            claude.write_text(f"#!{sys.executable}\nimport json, sys\nassert sys.argv[1:] == ['auth', 'status', '--json']\n"
                              f"print(json.dumps({STATUS_OK!r}))\n")
            claude.chmod(0o700)
            with patch.dict(os.environ, {"PATH": tmp}):
                self.assertEqual(verificar_login(), LOGIN_OK)
            with patch.dict(os.environ, {"PATH": str(Path(tmp) / "vazio")}), \
                    self.assertRaisesRegex(ErroConfiguracao, "não está no PATH"):
                verificar_login()


class TestInit(unittest.TestCase):
    BOM = {"tools": KORDA, "mcp_servers": [{"name": "korda", "status": "connected"}], "plugins": [],
           "apiKeySource": "none", "skills": [], "agents": ["general-purpose"], "slash_commands": ["compact", "cost"]}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        (self.home / ".claude/skills/minha-skill").mkdir(parents=True)
        (self.home / ".claude/agents").mkdir(parents=True)
        (self.home / ".claude/agents/revisor.md").write_text("x")

    def _verificar(self, **troca):
        verificar_init({**self.BOM, **troca}, ferramentas_esperadas=set(KORDA), home=self.home)

    def test_sessao_isolada_passa(self):
        self._verificar()
        verificar_init({**self.BOM, "tools": [], "mcp_servers": []}, ferramentas_esperadas=set(), home=self.home)

    def test_plugins_embutidos_do_cli_passam_e_os_do_disco_nao(self):
        # Achado do primeiro ensaio real: o --safe-mode mantém os cc-plugin-* do binário do CLI.
        (self.home / ".claude/plugins").mkdir(parents=True)
        (self.home / ".claude/plugins/installed_plugins.json").write_text(
            json.dumps({"version": 2, "plugins": {"cc-plugin-falso@mercado": []}}))
        embutidos = [{"name": "cc-plugin-privacy", "path": "/$bunfs/root/privacy"},
                     {"name": "cc-plugin-agents-md", "path": "builtin"}]
        self._verificar(plugins=embutidos)
        cache = str(self.home / ".claude/plugins/cache/mercado/cc-plugin-x/1.0")
        for plugin in ({"name": "cc-plugin-x", "path": cache}, {"name": "cc-plugin-falso", "path": "/$bunfs/x"},
                       {"name": "cc-plugin-y", "path": "/tmp/cwd-da-sessao/plug"}, "cc-plugin-z"):
            with self.subTest(plugin=plugin), self.assertRaises(ErroSegurancaHarness):
                self._verificar(plugins=embutidos + [plugin], cwd="/tmp/cwd-da-sessao")

    def test_aborta_com_qualquer_vazamento(self):
        casos = {"embutida": {"tools": KORDA + ["Bash"]}, "mcp": {"mcp_servers": [{"name": "github"}]},
                 "plugin": {"plugins": [{"name": "superpowers", "path": "/p"}]},
                 "chave": {"apiKeySource": "ANTHROPIC_API_KEY"}, "skill": {"skills": ["minha-skill"]},
                 "agente": {"agents": ["general-purpose", "revisor"]},
                 "comando": {"slash_commands": ["compact", "plugin:minha-skill"]},
                 "sem_korda": {"tools": KORDA[:2]}}
        for nome, troca in casos.items():
            with self.subTest(nome), self.assertRaises(ErroSegurancaHarness):
                self._verificar(**troca)


class TestExecutorClaudeCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.emissor = EmissorEventos(Path(self.tmp.name) / "eventos.jsonl", "run-teste")
        self.medidor = Medidor("run-teste", "claude_cli", "sonnet")
        self.f = FerramentasFalsas(dict.fromkeys(MODELOS, ""), MODELOS)

    def _executor(self, sessao):
        return ExecutorClaudeCli(_cfg(), self.f, projetar_plano(PLANO), {"cte": {}}, 3, self.emissor, self.medidor,
                                 rodar_sessao=sessao, esquema_bronze="- main.bronze_ctes: chave varchar")

    def _fim(self):
        return [e["dados"] for e in self.emissor.ler() if e["type"] == "agent_finished"]

    def test_constroi_e_corrige_com_os_tetos_e_a_medicao_por_assinatura(self):
        sessao = SessaoFalsa([{"escreve": MODELOS, "custo": 1.0, "turnos": 30}, {"escreve": MODELOS[:1], "custo": 0.3}])
        executor = self._executor(sessao)
        self.assertEqual(executor.construir("# Especificação"), {"ok": True, "custo_centavos": 600})
        self.assertEqual(executor(FALHA, 1), {"ok": True, "custo_centavos": 180})
        (p_construcao, construcao_ctx), (p_correcao, correcao_ctx) = sessao.chamadas
        self.assertEqual((construcao_ctx.sistema, construcao_ctx.max_turns), (SISTEMA_CONSTRUCAO, 40))
        self.assertEqual((correcao_ctx.sistema, correcao_ctx.max_turns), (SISTEMA, 12))
        self.assertAlmostEqual(construcao_ctx.max_budget_usd, 3.0 * 0.6 * 0.9)
        self.assertAlmostEqual(correcao_ctx.max_budget_usd, 2.0 / 3 * 0.9)
        self.assertIn("# Especificação", p_construcao)
        self.assertIn("main.bronze_ctes: chave varchar", p_construcao)
        self.assertIn("chave_fiscal_unica", p_correcao)
        fim = self._fim()
        self.assertEqual([d["fase"] for d in fim], ["construcao", "correcao"])
        for d in fim:
            self.assertEqual((d["cobranca"], d["custo_estimado"], d["modelo"]), ("assinatura", True, "claude-sonnet-5-5"))
            self.assertEqual(d["ferramentas"], KORDA)
            self.assertEqual(d["tokens_entrada"], 1000)  # entrada + criação + leitura de cache
        resumo = self.medidor.resumo()
        self.assertEqual((resumo["cobranca"], resumo["synthetic"], resumo["tentativas"]), ("assinatura", False, 2))
        self.assertEqual(resumo["tokens_cache_leitura"], 1000)

    def test_limite_de_uso_escala_sem_nova_sessao(self):
        sessao = SessaoFalsa([{"escreve": MODELOS, "custo": 0.5, "limite": True,
                               "erro": "limite de uso do plano: five_hour, reinicia em 1764000000"}])
        executor = self._executor(sessao)
        resultado = executor.construir(None)
        self.assertFalse(resultado["ok"])
        self.assertEqual(resultado["codigo"], "limite_uso")
        self.assertIn("uma pessoa decide", resultado["erro"])
        self.assertIn("five_hour", self._fim()[0]["erro_api"])
        self.assertTrue(self._fim()[0]["limite_uso"])
        segunda = executor(FALHA, 1)
        self.assertEqual((segunda["ok"], segunda["codigo"]), (False, "limite_uso"))
        self.assertEqual(len(sessao.chamadas), 1)

    def test_freio_do_orcamento_nocional(self):
        # Até a fatia sem a folga (1,80) é o freio do CLI funcionando; acima, recusa.
        self.assertTrue(self._executor(SessaoFalsa([{"escreve": MODELOS, "custo": 1.70}])).construir(None)["ok"])
        resultado = self._executor(SessaoFalsa([{"escreve": MODELOS, "custo": 1.90}])).construir(None)
        self.assertFalse(resultado["ok"])
        self.assertIn("orçamento", resultado["erro"])

    def test_sem_escrita_ou_com_erro_de_execucao_falha(self):
        for sessao in ({"subtype": "error_max_turns"}, {"subtype": "error_during_execution", "escreve": MODELOS},
                       {"subtype": "sem_resultado", "escreve": MODELOS, "custo": None}):
            with self.subTest(sessao["subtype"]):
                self.assertFalse(self._executor(SessaoFalsa([sessao])).construir(None)["ok"])

    def test_sessao_insegura_aborta_sem_escrita(self):
        with self.assertRaises(ErroSegurancaHarness):
            self._executor(SessaoFalsa([ErroSegurancaHarness("init com Bash")])).construir(None)
        self.assertEqual(self.f.escritas(), [])


class TestPlanejarPeloCli(unittest.TestCase):
    def setUp(self):
        from services.planning.korda_planning import gerar_plano

        self.contexto = json.loads(CONTEXTO.read_text(encoding="utf-8"))
        self.plano = gerar_plano(self.contexto, destino="pasta-demo", custo_estimado_centavos=0)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _planejar(self, sessao, login=lambda: LOGIN_OK):
        cliente = ClienteClaudeCli(_cfg(), rodar_sessao=sessao)
        with patch.object(agente_sdk, "verificar_login", side_effect=login):
            return planejamento.planejar(self.plano, self.contexto, raiz=Path(self.tmp.name), cfg=_cfg(),
                                         cliente_llm=cliente)

    def test_planeja_numa_sessao_sem_ferramentas_e_mede_por_assinatura(self):
        sessao = SessaoFalsa([{"texto": _decisao(True), "custo": 0.12, "turnos": 1}])
        r = self._planejar(sessao)
        self.assertEqual(r["estado"], "pronto")
        prompt, ctx = sessao.chamadas[0]
        self.assertIsNone(ctx.ferramentas)
        self.assertIsNone(ctx.hook)
        self.assertEqual((ctx.sistema, ctx.max_turns), (SISTEMA_DOCUMENTO, 1))
        self.assertIn("Contexto validado", prompt)
        self.assertEqual(r["plano"]["construction"]["model"], "sonnet")
        self.assertFalse(r["plano"]["construction"]["synthetic"])
        medicao = json.loads((Path(r["pasta"]) / "medicao.json").read_text())
        self.assertEqual((medicao["executor"], medicao["cobranca"], medicao["custo_estimado"]),
                         ("claude_cli", "assinatura", True))
        self.assertEqual(medicao["custo_nocional_cli_usd"], 0.12)
        self.assertEqual(medicao["tokens_entrada"], 1000)

    def test_sem_login_nao_abre_sessao(self):
        sessao = SessaoFalsa([])

        def sem_login():
            raise ErroConfiguracao("o CLI não está logado; faça `claude /login`")
        with self.assertRaisesRegex(FalhaExecucao, "/login"):
            self._planejar(sessao, login=sem_login)
        self.assertEqual(sessao.chamadas, [])

    def test_limite_de_uso_vira_falha_do_planejamento(self):
        sessao = SessaoFalsa([{"subtype": "success", "limite": True, "erro": "limite de uso do plano: HTTP 429"}])
        with self.assertRaisesRegex(FalhaExecucao, "provedor"):
            self._planejar(sessao)
        self.assertEqual(len(sessao.chamadas), 1)


class TestConstrucaoPeloWorker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        self.eventos = EmissorEventos(self.raiz / "eventos.jsonl", "run-cli")
        self.modelos = sorted(p.relative_to(construcao.PROJETO).as_posix() for p in (construcao.PROJETO / "models").glob("*.sql"))
        self.plano = {
            "construction": {"document": "\n".join("## " + t for t in SECOES), "model": "sonnet", "synthetic": False},
            "plan_version": "d" * 64, "limits": {"max_repair_attempts_per_step": 3}, "editable_models": self.modelos,
            "rules": {"rateio_cte": {"value": "peso"}}, "metrics": {"otif": {"unit": "%"}},
            "tasks": [{"id": "ouro", "depends_on": [], "verify": "conferir indicadores"}],
        }
        self.ferramentas = FerramentasFalsas(dict.fromkeys(self.modelos, ""), self.modelos)
        (self.raiz / "fontes.json").write_text(json.dumps({"erp_pedidos": {"colunas": ["cd_ped"]}}))

    def test_preparo_confere_o_login_e_o_documento(self):
        with patch.object(agente_sdk, "verificar_login", return_value=LOGIN_OK) as login:
            self.assertEqual(construcao.preparar_construcao(self.plano, _cfg()).executor, "claude_cli")
        login.assert_called_once()
        with patch.object(agente_sdk, "verificar_login", side_effect=ErroConfiguracao("faça `claude /login`")), \
                self.assertRaisesRegex(ErroConfiguracao, "/login"):
            construcao.preparar_construcao(self.plano, _cfg())
        sem_doc = dict(self.plano, construction={"document": " ", "model": "x", "synthetic": True})
        with patch.object(agente_sdk, "verificar_login", return_value=LOGIN_OK), \
                self.assertRaisesRegex(ErroConfiguracao, "construção"):
            construcao.preparar_construcao(sem_doc, _cfg())

    def test_constroi_pelo_cli_e_grava_a_medicao_por_assinatura(self):
        sessao = SessaoFalsa([{"escreve": self.modelos, "custo": 0.8, "turnos": 35}])
        with patch.object(agente_sdk, "verificar_login", return_value=LOGIN_OK), \
                patch.object(agente_sdk, "rodar_sessao_cli", side_effect=sessao), \
                patch.object(construcao, "ClienteChatHttp", side_effect=AssertionError("a Feita não entra")):
            resultado = construcao.construir_modelos(_cfg(), self.plano, self.ferramentas, self.eventos, self.raiz,
                                                     lambda: None)
        self.assertTrue(resultado["ok"], resultado)
        self.assertEqual(set(self.ferramentas.escritas()), set(self.modelos))
        medicao = json.loads((self.raiz / "medicao.json").read_text())
        self.assertEqual((medicao["executor"], medicao["construtor"], medicao["cobranca"]),
                         ("claude_cli", "claude_cli", "assinatura"))
        self.assertTrue(medicao["custo_estimado"])
        self.assertFalse(medicao["synthetic"])
        self.assertEqual(medicao["turnos"], 35)
        salvo = [e for e in self.eventos.ler() if e["type"] == "measurement_saved"][0]["dados"]
        self.assertEqual(salvo["cobranca"], "assinatura")


@unittest.skipUnless(SDK_INSTALADO, "claude-agent-sdk não instalado (requirements-harness.txt)")
class TestOpcoesAssinatura(unittest.TestCase):
    def test_opcoes_isolam_a_sessao_e_nao_levam_chave(self):
        from claude_agent_sdk import create_sdk_mcp_server

        servidor = create_sdk_mcp_server(name="korda", tools=[])
        with tempfile.TemporaryDirectory() as vazio:
            opcoes = agente_sdk.construir_opcoes(_cfg(), servidor, lambda *a: {}, Path(vazio), 1.62,
                                                 sistema=SISTEMA_CONSTRUCAO, max_turns=40, cli_path="/tmp/lancador")
        self.assertEqual(opcoes.cli_path, "/tmp/lancador")
        self.assertTrue(opcoes.strict_mcp_config)
        self.assertEqual(opcoes.setting_sources, [])
        self.assertEqual(opcoes.extra_args, ARGS_ASSINATURA)
        self.assertEqual(opcoes.env, {})
        self.assertEqual(opcoes.tools, [])
        self.assertEqual(set(opcoes.disallowed_tools), set(agente_sdk.EMBUTIDAS))
        self.assertEqual(sorted(opcoes.allowed_tools), KORDA)
        self.assertEqual((opcoes.permission_mode, opcoes.max_turns, opcoes.model), ("dontAsk", 40, "sonnet"))
        self.assertAlmostEqual(opcoes.max_budget_usd, 1.62)
        self.assertEqual(opcoes.system_prompt, SISTEMA_CONSTRUCAO)

    def test_planejamento_sem_servidor_nem_hook_e_exige_lancador(self):
        with tempfile.TemporaryDirectory() as vazio:
            opcoes = agente_sdk.construir_opcoes(_cfg(), None, None, Path(vazio), 2.7, sistema="s", max_turns=1,
                                                 cli_path="/tmp/l")
            self.assertEqual((opcoes.mcp_servers, opcoes.allowed_tools, opcoes.hooks), ({}, [], {}))
            with self.assertRaises(ValueError):
                agente_sdk.construir_opcoes(_cfg(), None, None, Path(vazio), 1.0)


@unittest.skipUnless(SDK_INSTALADO, "claude-agent-sdk não instalado (requirements-harness.txt)")
class TestColetaDoStream(unittest.TestCase):
    """`_coletar` com o `query` do SDK trocado por mensagens roteirizadas."""

    def _coletar(self, mensagens, verificar=None):
        import claude_agent_sdk

        async def query(prompt, options):
            for m in mensagens:
                yield m
        with patch.object(claude_agent_sdk, "query", query):
            return asyncio.run(agente_sdk._coletar("p", None, verificar))

    def _init(self, **troca):
        from claude_agent_sdk import SystemMessage

        return SystemMessage(subtype="init", data={**TestInit.BOM, "model": "claude-sonnet-5-5", **troca})

    def _resultado(self, **troca):
        from claude_agent_sdk import ResultMessage

        campos = dict(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=2,
                      session_id="s", total_cost_usd=0.05, usage={"input_tokens": 10, "output_tokens": 5},
                      result="pronto", stop_reason="end_turn")
        return ResultMessage(**{**campos, **troca})

    def _assistente(self, ident, entrada):
        from claude_agent_sdk import AssistantMessage

        return AssistantMessage(content=[], model="claude-sonnet-5-5", message_id=ident,
                                usage={"input_tokens": entrada, "cache_read_input_tokens": 100, "output_tokens": 7})

    def test_sessao_normal(self):
        saida = self._coletar([self._init(), self._assistente("m1", 10), self._assistente("m1", 10),
                               self._assistente("m2", 20), self._resultado()])
        self.assertEqual((saida.subtype, saida.num_turns, saida.total_cost_usd), ("success", 2, 0.05))
        self.assertEqual(saida.tokens_por_turno, [[110, 7], [120, 7]])
        self.assertEqual((saida.modelo, saida.texto, saida.limite_uso, saida.erro),
                         ("claude-sonnet-5-5", "pronto", False, None))

    def test_init_inseguro_aborta_antes_do_modelo(self):
        verificar = lambda d: verificar_init(d, ferramentas_esperadas=set(KORDA), home=None)  # noqa: E731
        for init in (self._init(tools=KORDA + ["Read"]), self._init(apiKeySource="ANTHROPIC_API_KEY")):
            with self.subTest(init.data.get("apiKeySource")), self.assertRaises(ErroSegurancaHarness):
                self._coletar([init, self._resultado()], verificar)

    def test_limite_de_uso_do_plano(self):
        from claude_agent_sdk import RateLimitEvent, RateLimitInfo

        evento = RateLimitEvent(rate_limit_info=RateLimitInfo(status="rejected", resets_at=1764000000,
                                                              rate_limit_type="five_hour"), uuid="u",
                                session_id="s")
        saida = self._coletar([self._init(), evento, self._resultado(is_error=True, api_error_status=429,
                                                                     result="usage limit reached")])
        self.assertTrue(saida.limite_uso)
        self.assertIn("five_hour", saida.erro)
        saida = self._coletar([self._init(), self._resultado(is_error=True, api_error_status=429)])
        self.assertTrue(saida.limite_uso)
        self.assertIn("429", saida.erro)

    def test_erro_da_api_sem_limite_fica_registrado(self):
        saida = self._coletar([self._init(), self._resultado(is_error=True, api_error_status=500,
                                                             errors=["overloaded"])])
        self.assertFalse(saida.limite_uso)
        self.assertEqual(saida.erro, "HTTP 500: overloaded")


if __name__ == "__main__":
    unittest.main()
