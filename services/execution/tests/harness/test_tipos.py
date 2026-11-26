"""Contratos estreitos de que o harness depende."""

import unittest

from korda_execution.harness.tipos import FerramentasAgente, ResultadoTentativa, usd_para_centavos

from .fakes import FerramentasFalsas


class TestCusto(unittest.TestCase):
    def test_arredonda_para_cima_em_centavos_de_real(self):
        self.assertEqual(usd_para_centavos(0.0123, 6.0), 8)  # 7,38 centavos → 8

    def test_zero_e_zero(self):
        self.assertEqual(usd_para_centavos(0, 6.0), 0)

    def test_custo_desconhecido_continua_desconhecido(self):
        self.assertIsNone(usd_para_centavos(None, 6.0))

    def test_custo_negativo_e_recusado(self):
        with self.assertRaises(ValueError):
            usd_para_centavos(-0.01, 6.0)


class TestContratos(unittest.TestCase):
    def test_ferramentas_falsas_cumprem_o_protocolo(self):
        self.assertIsInstance(FerramentasFalsas({}, ["models/prata_ctes.sql"]), FerramentasAgente)

    def test_objeto_sem_metodos_nao_cumpre(self):
        self.assertNotIsInstance(object(), FerramentasAgente)

    def test_resultado_tentativa_serializa(self):
        r = ResultadoTentativa(tentativa=1, corretor="falso", ok=True, motivo_parada="success", turnos=2,
                               tokens_entrada=10, tokens_saida=5, tokens_cache_leitura=0, custo_usd=0.01,
                               custo_centavos=6, duracao_s=0.5, arquivos_escritos=["models/prata_ctes.sql"])
        self.assertEqual(r.como_dict()["arquivos_escritos"], ["models/prata_ctes.sql"])


if __name__ == "__main__":
    unittest.main()


class TestContratoComOWorker(unittest.TestCase):
    """Depois do merge do #21: a classe real cumpre a interface que o harness usa."""

    def test_ferramentas_restritas_cumprem_o_protocolo(self):
        import inspect
        import tempfile
        from pathlib import Path

        from korda_execution.eventos import EmissorEventos
        from korda_execution.ferramentas import FerramentasRestritas

        with tempfile.TemporaryDirectory() as d:
            real = FerramentasRestritas(sandbox=object(), eventos=EmissorEventos(Path(d) / "e.jsonl", "r"))
        self.assertIsInstance(real, FerramentasAgente)
        for nome in ("ler_plano", "inspecionar_fonte", "ler_arquivo", "escrever_modelo", "rodar_dbt", "consultar_sql"):
            with self.subTest(nome=nome):
                esperado = list(inspect.signature(getattr(FerramentasAgente, nome)).parameters)
                self.assertEqual(list(inspect.signature(getattr(FerramentasRestritas, nome)).parameters), esperado)
