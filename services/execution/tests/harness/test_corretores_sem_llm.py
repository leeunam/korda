"""Corretores sem LLM: o roteirizado (plano B da demo) e o falso (testes)."""

import tempfile
import unittest
from pathlib import Path

from korda_execution.eventos import EmissorEventos
from korda_execution.harness.config import ConfigHarness
from korda_execution.harness.falso import ClienteLLMFalso, CorretorFalso
from korda_execution.harness.politica import PREFIXO
from korda_execution.harness.roteirizado import CorretorRoteirizado
from korda_execution.harness.tipos import Corretor, usd_para_centavos

from .fakes import FerramentasFalsas

MODELO = "models/prata_ctes.sql"
CORRETO = "select distinct chave from ctes"
FALHA = {"ok": False, "codigo": "implementacao", "erro": "Failure in test chave_fiscal_unica"}


class TestRoteirizado(unittest.TestCase):
    def test_escreve_a_versao_revisada(self):
        f = FerramentasFalsas({MODELO: "select chave from ctes"}, [MODELO])
        corretor = CorretorRoteirizado(f, MODELO, lambda: CORRETO)
        self.assertIsInstance(corretor, Corretor)
        resultado = corretor(FALHA, 1)
        self.assertTrue(resultado["ok"])
        self.assertEqual(resultado["custo_centavos"], 0)
        self.assertEqual(f.modelos[MODELO], CORRETO)

    def test_ja_corresponde_nao_escreve(self):
        f = FerramentasFalsas({MODELO: CORRETO}, [MODELO])
        resultado = CorretorRoteirizado(f, MODELO, lambda: CORRETO)(FALHA, 1)
        self.assertFalse(resultado["ok"])
        self.assertIn("já corresponde", resultado["erro"])
        self.assertEqual(resultado["custo_centavos"], 0)
        self.assertEqual(f.escritas(), [])

    def test_leitura_falha(self):
        f = FerramentasFalsas({}, [MODELO])
        resultado = CorretorRoteirizado(f, MODELO, lambda: CORRETO)(FALHA, 1)
        self.assertFalse(resultado["ok"])
        self.assertEqual(resultado["custo_centavos"], 0)


class TestFalso(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.emissor = EmissorEventos(Path(self.tmp.name) / "eventos.jsonl", "run-teste")
        self.cfg = ConfigHarness.de_ambiente({"KORDA_CORRETOR": "falso"})
        self.f = FerramentasFalsas({MODELO: "select chave from ctes"}, [MODELO])

    def tearDown(self):
        self.tmp.cleanup()

    def _corretor(self, roteiro):
        cliente = ClienteLLMFalso(roteiro, tokens_por_turno=(1000, 200), custo_usd_por_turno=0.01)
        return CorretorFalso(cliente, self.f, [MODELO], self.cfg, emissor=self.emissor)

    def test_corrige_quando_o_roteiro_escreve_o_modelo(self):
        roteiro = [[(PREFIXO + "ler_arquivo", {"caminho": MODELO}),
                    (PREFIXO + "escrever_modelo", {"caminho": MODELO, "conteudo": CORRETO}),
                    (PREFIXO + "rodar_dbt", {"subcomando": "build"})]]
        resultado = self._corretor(roteiro)(FALHA, 1)
        self.assertTrue(resultado["ok"])
        self.assertEqual(resultado["custo_centavos"], usd_para_centavos(0.01 * 3, 6.0))
        self.assertEqual(self.f.modelos[MODELO], CORRETO)

    def test_roteiro_vazio_nao_altera_nada(self):
        resultado = self._corretor([])(FALHA, 1)
        self.assertFalse(resultado["ok"])
        self.assertIn("sem alteração", resultado["erro"])
        self.assertIsInstance(resultado["custo_centavos"], int)

    def test_escrita_em_teste_e_recusada_antes_da_ferramenta(self):
        roteiro = [[(PREFIXO + "escrever_modelo", {"caminho": "tests/chave_fiscal_unica.sql", "conteudo": "select 1"}),
                    ("Bash", {"command": "rm -rf /work"})]]
        resultado = self._corretor(roteiro)(FALHA, 1)
        self.assertFalse(resultado["ok"])
        self.assertEqual([n for n, _ in self.f.chamadas if n.startswith("escrever")], [])
        recusas = [e for e in self.emissor.ler() if e["type"] == "tool_refused"]
        self.assertEqual(len(recusas), 2)
        self.assertTrue(all(e["dados"]["origem"] == "hook" for e in recusas))

    def test_cada_tentativa_consome_um_item_do_roteiro(self):
        escrita = [(PREFIXO + "escrever_modelo", {"caminho": MODELO, "conteudo": CORRETO})]
        corretor = self._corretor([escrita, []])
        self.assertTrue(corretor(FALHA, 1)["ok"])
        self.assertFalse(corretor(FALHA, 2)["ok"])
        self.assertFalse(corretor(FALHA, 3)["ok"])


if __name__ == "__main__":
    unittest.main()
