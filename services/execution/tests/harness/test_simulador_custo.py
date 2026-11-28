"""Simulador de custo da construção: as otimizações reduzem a entrada estimada (sem LLM)."""

import unittest

from korda_execution.harness.contexto import SISTEMA_CONSTRUCAO

from .simulador_custo import PROJETO, roteiro_longo, roteiro_tipico, simular


class TestSimuladorCusto(unittest.TestCase):
    def test_compactar_historico_reduz_a_entrada_acumulada(self):
        for nome, roteiro in (("típico", roteiro_tipico), ("longo", roteiro_longo)):
            with self.subTest(nome):
                sem = simular(nome, roteiro(), manter_turnos=None)
                com = simular(nome, roteiro())
                self.assertEqual((sem.subtype, com.subtype), ("success", "success"))
                self.assertEqual(sem.turnos, com.turnos)
                self.assertLess(com.entrada, sem.entrada * 0.8)
                self.assertLess(com.maior_pedido, sem.maior_pedido)

    def test_construcao_longa_cabe_no_teto_e_nos_turnos(self):
        r = simular("longo", roteiro_longo())
        self.assertEqual(r.subtype, "success")
        self.assertLess(r.usd, 7.50 * 0.6 * 0.9)

    def test_prompt_nao_traz_modelos_de_referencia(self):
        from korda_execution.harness.contexto import montar_prompt_construcao
        from .simulador_custo import DOCUMENTO, PERFIS, plano_publico

        texto = SISTEMA_CONSTRUCAO + montar_prompt_construcao(plano_publico(), PERFIS, DOCUMENTO.read_text())
        for modelo in (PROJETO / "models").glob("*.sql"):
            for linha in modelo.read_text().splitlines():
                if len(linha.strip()) > 40:
                    self.assertNotIn(linha.strip(), texto, f"{modelo.name} vazou no prompt")


if __name__ == "__main__":
    unittest.main()
