"""O exemplo real do planejamento (fixture sintética) segue o contrato atual, sem LLM."""

import json
import unittest
from pathlib import Path

from korda_execution.contrato_saida import contrato_saida
from korda_execution.documento_base import SECOES, ler_decisao

FIXTURES = Path(__file__).resolve().parent / "fixtures/planejamento"


class TestFixturePlanejamento(unittest.TestCase):
    def test_documento_aprovavel_usa_os_nomes_fixos(self):
        texto = (FIXTURES / "02_rateio_confirmado.md").read_text(encoding="utf-8")
        self.assertTrue(texto.startswith("<!-- SINTÉTICO"))
        for secao in SECOES:
            self.assertIn(f"## {secao}", texto)
        self.assertNotIn("pronto_para_construir", texto)  # a decisão foi removida antes de anexar
        for modelo in contrato_saida()["modelos"]:  # se o contrato mudar, a fixture precisa ser refeita
            self.assertIn(modelo, texto)

    def test_perguntas_sao_validas(self):
        saida = json.loads((FIXTURES / "01_rateio_pendente.perguntas.json").read_text(encoding="utf-8"))
        self.assertTrue(saida["nota"].startswith("SINTÉTICO"))
        bloco = json.dumps({"pronto_para_construir": False, "perguntas": saida["perguntas"]}, ensure_ascii=False)
        self.assertEqual(ler_decisao(f"```json\n{bloco}\n```"), (False, saida["perguntas"]))


if __name__ == "__main__":
    unittest.main()
