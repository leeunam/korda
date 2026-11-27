"""Aceites do worker com a imagem real e o lote 01_demo, sem LLM.

O executor `falso` passa pelo mesmo caminho do `chat` (ExecutorChat, hook, ferramentas,
sandbox), com respostas roteiradas pelo ClienteChatFalso. O `roteirizado` é o plano B.
"""

import hashlib
import json
import os
import re
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from korda_execution.eventos import EmissorEventos
from korda_execution.harness.cliente_chat import ClienteChatFalso, RespostaChat
from korda_execution.harness.config import ConfigHarness
from korda_execution.sandbox import IMAGEM_PADRAO, docker_disponivel, imagem_existe

REPO = Path(__file__).resolve().parents[3]
CONTEXTO = REPO / "packages/contracts/context/v0.1.0/examples/02_rateio_confirmado.json"
_PRONTO = docker_disponivel() and imagem_existe(IMAGEM_PADRAO)
if not _PRONTO and os.environ.get("KORDA_EXIGIR_DOCKER") == "1":
    raise RuntimeError(f"KORDA_EXIGIR_DOCKER=1, mas Docker ou a imagem {IMAGEM_PADRAO} não está disponível")


def _hashes(*pastas):
    return {str(c): hashlib.sha256(c.read_bytes()).hexdigest()
            for pasta in pastas for c in sorted(pasta.rglob("*")) if c.is_file() and "__pycache__" not in c.parts}


def _sem_deduplicacao(sql):
    # Omite a seleção da primeira cópia do documento: o teste protegido chave_fiscal_unica falha.
    defeituoso, n = re.subn(r"(?im)^where\s+copia\s*=\s*1\s*;?\s*\Z", "", sql)
    assert n == 1, "a fixture precisa acompanhar o modelo de deduplicação atual"
    return defeituoso


PRONTO = '\n```json\n{"pronto_para_construir": true, "perguntas": []}\n```\n'


def _escreve(modelos):
    return RespostaChat.de_tool_calls([("escrever_modelo", {"caminho": c, "conteudo": s})
                                       for c, s in sorted(modelos.items())])


@unittest.skipUnless(_PRONTO, f"Docker ou imagem {IMAGEM_PADRAO} indisponível")
class TestWorkerDocker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from data.synthetic.generator.generate import generate

        cls.tmp_classe = tempfile.TemporaryDirectory()
        cls.fontes = Path(cls.tmp_classe.name) / "fontes"
        generate("01_demo", output_root=cls.fontes)

    @classmethod
    def tearDownClass(cls):
        cls.tmp_classe.cleanup()

    def setUp(self):
        from korda_execution import worker
        from korda_execution.aprovacoes import Registro
        from services.planning.korda_planning import gerar_plano

        self.worker = worker
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.contexto = json.loads(CONTEXTO.read_text(encoding="utf-8"))
        self.plano = gerar_plano(self.contexto, destino="pasta-demo", custo_estimado_centavos=0)
        self.assertEqual(self.plano["editable_models"], ["models/*"])
        self.registro = Registro(self.base / "controle")
        self.registro.registrar(self.plano)
        self.registro.decidir_plano(self.plano["project_id"], self.plano["plan_version"], "Pessoa fictícia (teste)", True)
        self.run_id = "e2e-" + uuid.uuid4().hex
        self.protegidos = (worker.PROJETO / "tests", worker.PROJETO / "definicoes", worker.PROJETO / "models")
        self.hashes = _hashes(*self.protegidos)

    def _executar(self, executor, cliente=None):
        cfg = ConfigHarness.de_ambiente({"KORDA_EXECUTOR": executor})
        return self.worker.executar(self.registro, self.plano, self.run_id, raiz=self.base,
                                    fontes=self.fontes / "01_demo", contexto=self.contexto, cfg=cfg,
                                    cliente_llm=cliente)

    def _eventos(self):
        return EmissorEventos(self.base / "revisao" / self.run_id / "eventos.jsonl", self.run_id).ler()

    def _arquivo(self, nome):
        return self.base / "revisao" / self.run_id / nome

    def tearDown(self):
        self.assertFalse((self.base / "sandbox" / self.run_id).exists(), "a sandbox temporária deve ser removida")
        self.assertEqual(_hashes(*self.protegidos), self.hashes, "testes, definições e pipeline à mão intactos")

    def test_agente_falso_constroi_de_models_vazio_e_a_avaliacao_aprova(self):
        modelos = self.worker.modelos_a_mao()
        cliente = ClienteChatFalso([
            RespostaChat.texto("## Modelos\n…\n## Regras aplicadas\n…\n## Métricas\n…\n## Testes de aceite\n…\n"
                               "## Premissas e lacunas\n…" + PRONTO, tokens=(3000, 800)),
            RespostaChat.de_tool_calls([("ler_arquivo", {"caminho": "exportar.py"})]),
            # Escrita em teste protegido: o hook recusa antes de chegar às ferramentas.
            RespostaChat.de_tool_calls([("escrever_modelo", {"caminho": "tests/chave_fiscal_unica.sql",
                                                             "conteudo": "select 1 where false"})]),
            _escreve(modelos),
            RespostaChat.texto("Pipeline escrito."),
        ])
        estado = self._executar("falso", cliente)
        self.assertEqual(estado["state"], "aguardando_aprovacao_entrega", estado)
        self.assertIn("Contexto validado", cliente.pedidos[0][1]["content"])
        self.assertIn("SINTÉTICO", self._arquivo("documento_base.md").read_text(encoding="utf-8"))
        self.assertIn("## Métricas", cliente.pedidos[1][1]["content"])  # o documento-base chega ao harness

        eventos = self._eventos()
        recusa = [e for e in eventos if e["type"] == "tool_refused"]
        self.assertEqual(len(recusa), 1)
        self.assertEqual(recusa[0]["dados"]["origem"], "hook")
        escritos = sorted(e["dados"]["caminho"] for e in eventos if e["type"] == "file_written")
        self.assertEqual(escritos, sorted(modelos))
        sequencia = {"build_started", "agent_finished", "dbt_passed", "test_passed", "evaluation_finished",
                     "intervention_requested"}
        self.assertEqual([e["type"] for e in eventos if e["type"] in sequencia],
                         ["build_started", "agent_finished", "dbt_passed", "test_passed", "evaluation_finished"])
        self.assertTrue(eventos[-1]["dados"]["aprovado"])
        custo = [e for e in eventos if e["type"] == "agent_finished"][0]["dados"]
        self.assertGreater(custo["custo_total_centavos"], custo["custo_centavos"])  # inclui o documento-base

        medicao = json.loads(self._arquivo("medicao.json").read_text(encoding="utf-8"))
        self.assertTrue(medicao["synthetic"])
        self.assertEqual(medicao["executor"], "falso")
        self.assertEqual(medicao["documento_base"]["tokens_entrada"], 3000)
        self.assertEqual([t["tentativa"] for t in medicao["por_tentativa"]], [0])

    def test_falha_sem_solucao_para_no_limite_e_nao_avalia(self):
        modelos = self.worker.modelos_a_mao()
        ruim = {**modelos, self.worker.MODELO_CTE: _sem_deduplicacao(modelos[self.worker.MODELO_CTE])}
        corrige_errado = _escreve({self.worker.MODELO_CTE: ruim[self.worker.MODELO_CTE]})
        cliente = ClienteChatFalso([
            RespostaChat.texto("## Modelos\n" + PRONTO), _escreve(ruim), RespostaChat.texto("pronto"),
            corrige_errado, RespostaChat.texto("tentei"),
            corrige_errado, RespostaChat.texto("tentei"),
            corrige_errado, RespostaChat.texto("tentei"),
        ])
        with self.assertRaisesRegex(self.worker.FalhaExecucao, "limite_atingido"):
            self._executar("falso", cliente)
        self.assertEqual(self.registro.consultar(self.run_id)["state"], "falhou")
        eventos = self._eventos()
        tipos = [e["type"] for e in eventos]
        self.assertEqual(tipos.count("intervention_requested"), 1)
        self.assertEqual(tipos.count("fix_applied"), 3)
        self.assertEqual(tipos.count("test_failed"), 4)
        self.assertNotIn("evaluation_finished", tipos)
        falha = [e for e in eventos if e["type"] == "test_failed"][0]
        self.assertEqual(falha["dados"]["codigo"], "implementacao")
        intervencao = [e for e in eventos if e["type"] == "intervention_requested"][0]
        self.assertEqual(intervencao["dados"]["codigo"], "limite_atingido")
        self.assertFalse(self._arquivo("avaliacao.json").exists())
        self.assertEqual(json.loads(self._arquivo("medicao.json").read_text())["tentativas"], 4)

    def test_construcao_sem_modelos_escala_sem_build(self):
        cliente = ClienteChatFalso([RespostaChat.texto("## Modelos\n" + PRONTO), RespostaChat.texto("Não consigo.")])
        with self.assertRaisesRegex(self.worker.FalhaExecucao, "construcao_falhou"):
            self._executar("falso", cliente)
        tipos = [e["type"] for e in self._eventos()]
        self.assertEqual(tipos.count("intervention_requested"), 1)
        self.assertNotIn("dbt_failed", tipos)
        self.assertNotIn("evaluation_finished", tipos)

    def test_roteirizado_continua_passando_ponta_a_ponta(self):
        modelos = self.worker.modelos_a_mao()
        ruim = {**modelos, self.worker.MODELO_CTE: _sem_deduplicacao(modelos[self.worker.MODELO_CTE])}
        with patch.object(self.worker, "modelos_a_mao", return_value=ruim):
            estado = self._executar("roteirizado")
        self.assertEqual(estado["state"], "aguardando_aprovacao_entrega", estado)
        eventos = self._eventos()
        sequencia = {"dbt_failed", "test_failed", "fix_started", "fix_applied", "dbt_passed", "test_passed",
                     "evaluation_finished"}
        self.assertEqual([e["type"] for e in eventos if e["type"] in sequencia], [
            "dbt_failed", "test_failed", "fix_started", "fix_applied", "dbt_passed", "test_passed",
            "evaluation_finished"])
        por_tipo = {e["type"]: e for e in eventos}
        self.assertEqual(por_tipo["test_failed"]["dados"]["codigo"], "implementacao")
        self.assertEqual(por_tipo["dbt_passed"]["attempt"], 2)
        self.assertEqual(por_tipo["fix_applied"]["dados"]["custo_centavos"], 0)
        self.assertIn("Não gerado", self._arquivo("documento_base.md").read_text(encoding="utf-8"))
        self.assertTrue(json.loads(self._arquivo("medicao.json").read_text())["synthetic"])


if __name__ == "__main__":
    unittest.main()
