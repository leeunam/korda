"""Adaptador provisório: eventos do worker → RunEvent do front (events.schema.json)."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from korda_execution.harness.adaptador_eventos import MAPA, exportar_execucao, traduzir

RAIZ = Path(__file__).resolve().parents[4]
SCHEMA = RAIZ / "packages/contracts/events.schema.json"
TEM_JSONSCHEMA = importlib.util.find_spec("jsonschema") is not None


def _ev(step, type, attempt=1, **dados):
    ev = {"run_id": "run-1", "step": step, "type": type, "message": f"{step}/{type}", "attempt": attempt,
          "ts": "2026-11-25T12:00:00.000+00:00"}
    if dados:
        ev["dados"] = dados
    return ev


class TestTraduzir(unittest.TestCase):
    def test_tabela_provisoria(self):
        casos = [
            (_ev("plano", "run_started"), ("plan", "task_started")),
            (_ev("modelos", "test_failed"), ("run_dbt", "test_failed")),
            (_ev("modelos", "test_passed"), ("run_dbt", "test_passed")),
            (_ev("modelos", "fix_started"), ("agent", "task_started")),
            (_ev("modelos", "fix_applied"), ("agent", "fix_applied")),
            (_ev("construcao", "file_written", caminho="models/prata_ctes.sql"), ("agent", "file_written")),
            (_ev("construcao", "tool_refused", ferramenta="escrever_modelo"), ("write_hook", "write_blocked")),
            (_ev("construcao", "tool_refused", ferramenta="Bash", origem="hook"), ("write_hook", "write_blocked")),
        ]
        for evento, esperado in casos:
            with self.subTest(evento=evento["type"]):
                traduzido = traduzir(evento)
                self.assertEqual((traduzido["step"], traduzido["type"]), esperado)
                self.assertNotIn("dados", traduzido)

    def test_arquivo_escrito_vira_data_file(self):
        traduzido = traduzir(_ev("construcao", "file_written", caminho="models/prata_ctes.sql", bytes=10))
        self.assertEqual(traduzido["data"]["file"], "models/prata_ctes.sql")
        self.assertEqual(traduzido["data"]["bytes"], 10)

    def test_recusa_de_leitura_nao_vira_bloqueio_de_escrita(self):
        self.assertIsNone(traduzir(_ev("construcao", "tool_refused", ferramenta="ler_arquivo")))

    def test_nao_mapeados(self):
        for step, type in (("modelos", "intervention_requested"), ("avaliacao", "evaluation_finished"),
                           ("execucao", "run_failed"), ("construcao", "agent_finished"),
                           ("construcao", "dbt_failed"), ("construcao", "query_finished")):
            with self.subTest(type=type):
                self.assertIsNone(traduzir(_ev(step, type)))

    def test_tentativa_fora_de_1_a_3(self):
        traduzido = traduzir(_ev("modelos", "test_passed", attempt=4))
        self.assertIsNone(traduzido["attempt"])
        self.assertEqual(traduzido["data"]["attempt_original"], 4)
        self.assertEqual(traduzir(_ev("modelos", "test_passed", attempt=2))["attempt"], 2)

    @unittest.skipUnless(TEM_JSONSCHEMA, "jsonschema não instalado (requirements-contracts.txt)")
    def test_saida_valida_no_contrato(self):
        import jsonschema

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        eventos = [_ev(s, t, attempt=4, caminho="models/x.sql", ferramenta="escrever_modelo") for s, t in MAPA]
        for evento in eventos:
            with self.subTest(evento=evento["type"]):
                jsonschema.validate(traduzir(evento), schema)


class TestExportar(unittest.TestCase):
    def test_exporta_no_formato_do_seed(self):
        eventos = [_ev("plano", "run_started"), _ev("modelos", "test_failed"), _ev("modelos", "fix_started"),
                   _ev("construcao", "agent_finished"), _ev("construcao", "agent_finished"),
                   _ev("modelos", "intervention_requested")]
        with tempfile.TemporaryDirectory() as d:
            jsonl = Path(d) / "eventos.jsonl"
            jsonl.write_text("".join(json.dumps(e) + "\n" for e in eventos), encoding="utf-8")
            saida = exportar_execucao(jsonl, synthetic=True)
            cli = subprocess.run([sys.executable, "-m", "korda_execution.harness.adaptador_eventos", str(jsonl),
                                  "--synthetic"], capture_output=True, text=True, check=True,
                                 cwd=RAIZ / "services/execution")
        self.assertEqual(saida["run_id"], "run-1")
        self.assertTrue(saida["synthetic"])
        self.assertIn("provisório", saida["note"])
        self.assertEqual([e["type"] for e in saida["events"]], ["task_started", "test_failed", "task_started"])
        self.assertEqual(saida["nao_mapeados"], {"construcao/agent_finished": 2, "modelos/intervention_requested": 1})
        self.assertEqual(json.loads(cli.stdout), saida)

    def test_arquivo_vazio(self):
        with tempfile.TemporaryDirectory() as d:
            jsonl = Path(d) / "eventos.jsonl"
            jsonl.write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                exportar_execucao(jsonl, synthetic=False)


if __name__ == "__main__":
    unittest.main()
