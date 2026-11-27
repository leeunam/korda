"""Orquestração construção → build → correções, com etapa e construtor falsos (sem LLM, sem #21)."""

import unittest

from korda_execution.harness.orquestracao import construir_e_verificar


class Construtor:
    def __init__(self, resultado):
        self.resultado = resultado
        self.documentos = []

    def construir(self, documento_base):
        self.documentos.append(documento_base)
        return self.resultado


def etapa_falsa(tentar, corrigir, registrar, *, limite):
    """Imita executar_etapa do #21: testa, corrige até o limite, escala."""
    for tentativa in range(1, limite + 2):
        r = tentar()
        if r["ok"]:
            registrar("test_passed", {"tentativas": tentativa})
            return {"ok": True, "tentativas": tentativa}
        if tentativa > limite:
            registrar("intervention_requested", {"tentativas": tentativa})
            return {"ok": False, "codigo": "limite_atingido", "tentativas": tentativa}
        corrigir(r, tentativa)


class TestOrquestracao(unittest.TestCase):
    def setUp(self):
        self.registros = []

    def _registrar(self, tipo, dados):
        self.registros.append(tipo)

    def test_constroi_e_passa_de_primeira(self):
        construtor = Construtor({"ok": True, "custo_centavos": 10})
        r = construir_e_verificar(construtor, lambda f, t: {"ok": True, "custo_centavos": 0},
                                  lambda: {"ok": True}, etapa_falsa, self._registrar, limite=3, documento_base="doc")
        self.assertTrue(r["ok"])
        self.assertEqual(r["construcao"], {"ok": True, "custo_centavos": 10})
        self.assertEqual(construtor.documentos, ["doc"])

    def test_construcao_que_falha_escala_sem_build(self):
        chamadas = []
        r = construir_e_verificar(Construtor({"ok": False, "erro": "sem alteração", "custo_centavos": 5}),
                                  lambda f, t: {"ok": True}, lambda: chamadas.append(1) or {"ok": True},
                                  etapa_falsa, self._registrar, limite=3, documento_base=None)
        self.assertFalse(r["ok"])
        self.assertEqual(r["codigo"], "construcao_falhou")
        self.assertEqual(chamadas, [])
        self.assertEqual(self.registros, ["intervention_requested"])

    def test_falha_no_build_entra_no_ciclo_de_correcao(self):
        builds = iter([{"ok": False, "codigo": "implementacao", "erro": "x"}] * 4)
        correcoes = []
        r = construir_e_verificar(Construtor({"ok": True, "custo_centavos": 0}),
                                  lambda f, t: correcoes.append(t) or {"ok": True, "custo_centavos": 0},
                                  lambda: next(builds), etapa_falsa, self._registrar, limite=3, documento_base=None)
        self.assertFalse(r["ok"])
        self.assertEqual(r["codigo"], "limite_atingido")
        self.assertEqual(correcoes, [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
