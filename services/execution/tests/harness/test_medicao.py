"""Medição por execução: tempo, tokens, tentativas e custo (insumo da K14)."""

import json
import tempfile
import unittest
from pathlib import Path

from korda_execution.harness.medicao import Medidor
from korda_execution.harness.tipos import ResultadoTentativa


def _tentativa(n, custo_usd=0.5, custo_centavos=300, ok=True):
    return ResultadoTentativa(tentativa=n, corretor="chat", ok=ok, motivo_parada="success", turnos=4,
                              tokens_entrada=1000, tokens_saida=200, tokens_cache_leitura=50, custo_usd=custo_usd,
                              custo_centavos=custo_centavos, duracao_s=10.0, arquivos_escritos=["models/prata_ctes.sql"])


class TestMedidor(unittest.TestCase):
    def test_soma_tentativas(self):
        m = Medidor("run-1", "chat", "claude-opus-5-5")
        m.registrar(_tentativa(1))
        m.registrar(_tentativa(2, custo_usd=0.25, custo_centavos=150, ok=False))
        r = m.resumo()
        self.assertEqual(r["tentativas"], 2)
        self.assertEqual(r["turnos"], 8)
        self.assertEqual(r["tokens_entrada"], 2000)
        self.assertEqual(r["tokens_saida"], 400)
        self.assertEqual(r["tokens_cache_leitura"], 100)
        self.assertAlmostEqual(r["custo_usd"], 0.75)
        self.assertEqual(r["custo_centavos"], 450)
        self.assertTrue(r["custo_completo"])
        self.assertAlmostEqual(r["duracao_s"], 20.0)
        self.assertEqual(len(r["por_tentativa"]), 2)
        self.assertFalse(r["synthetic"])

    def test_custo_desconhecido_marca_incompleto(self):
        m = Medidor("run-1", "chat", "claude-opus-5-5")
        m.registrar(_tentativa(1))
        m.registrar(_tentativa(2, custo_usd=None, custo_centavos=None))
        r = m.resumo()
        self.assertFalse(r["custo_completo"])
        self.assertEqual(r["custo_centavos"], 300)

    def test_sem_tentativas(self):
        r = Medidor("run-1", "roteirizado", None).resumo()
        self.assertEqual(r["tentativas"], 0)
        self.assertEqual(r["custo_centavos"], 0)
        self.assertTrue(r["custo_completo"])

    def test_sintetico_quando_nao_usa_llm(self):
        for executor in ("falso", "roteirizado"):
            self.assertTrue(Medidor("run-1", executor, None).resumo()["synthetic"])
        for executor in ("chat", "agente_sdk"):
            self.assertFalse(Medidor("run-1", executor, None).resumo()["synthetic"])

    def test_grava_json(self):
        m = Medidor("run-1", "falso", "claude-opus-5-5")
        m.registrar(_tentativa(1))
        with tempfile.TemporaryDirectory() as d:
            caminho = Path(d) / "sub" / "medicao.json"
            m.gravar(caminho)
            dados = json.loads(caminho.read_text(encoding="utf-8"))
        self.assertEqual(dados["run_id"], "run-1")
        self.assertEqual(dados["executor"], "falso")
        self.assertTrue(dados["synthetic"])
        self.assertNotIn("ANTHROPIC_API_KEY", json.dumps(dados))


if __name__ == "__main__":
    unittest.main()
