import sqlite3
import unittest
from unittest.mock import Mock

from korda_execution.correcao import executar_etapa


class TestCorrecao(unittest.TestCase):
    def setUp(self):
        self.eventos = []

    def registrar(self, tipo, dados):
        self.eventos.append((tipo, dados))

    def test_duplicata_exige_corrigir_modelo_e_revalidar(self):
        banco = sqlite3.connect(":memory:")
        self.addCleanup(banco.close)
        banco.execute("CREATE TABLE fonte (chave TEXT, centavos INTEGER)")
        banco.executemany("INSERT INTO fonte VALUES (?, ?)", [("A", 40000), ("A", 40000), ("B", 15000)])
        banco.execute("CREATE VIEW frete AS SELECT chave, centavos FROM fonte")
        encontrados = []

        def tentar():
            total, = banco.execute("SELECT SUM(centavos) FROM frete").fetchone()
            encontrados.append(total)
            return {"ok": total == 55000, "codigo": "implementacao", "erro": "Frete duplicado"}

        def corrigir(falha, numero):
            self.assertEqual((falha["codigo"], numero), ("implementacao", 1))
            banco.execute("DROP VIEW frete")
            banco.execute("CREATE VIEW frete AS SELECT DISTINCT chave, centavos FROM fonte")
            return {"ok": True, "custo_centavos": 7}

        resultado = executar_etapa(tentar, corrigir, self.registrar)
        self.assertEqual(encontrados, [95000, 55000])
        self.assertEqual(banco.execute("SELECT COUNT(*) FROM fonte").fetchone(), (3,))
        self.assertTrue(resultado["ok"])
        self.assertEqual((resultado["tentativas"], resultado["correcoes"], resultado["custo_centavos"]), (2, 1, 7))
        self.assertEqual([tipo for tipo, _ in self.eventos], ["test_failed", "fix_started", "fix_applied", "test_passed"])

    def test_falha_persistente_retenta_tres_vezes_e_escala(self):
        tentar = Mock(return_value={"ok": False, "codigo": "implementacao", "erro": "Modelo inconsistente"})
        custos = [1, 2, 3]
        corrigir = Mock(side_effect=[{"ok": True, "custo_centavos": c} for c in custos])
        resultado = executar_etapa(tentar, corrigir, self.registrar)
        self.assertFalse(resultado["ok"])
        self.assertEqual(resultado["codigo"], "limite_atingido")
        self.assertEqual((tentar.call_count, corrigir.call_count, resultado["custo_centavos"]), (4, 3, sum(custos)))
        self.assertEqual([c.args[1] for c in corrigir.call_args_list], [1, 2, 3])
        self.assertEqual(self.eventos[-1], ("intervention_requested", resultado))
        self.assertNotIn("test_passed", [t for t, _ in self.eventos])

    def test_regra_dados_erro_tecnico_ou_falha_desconhecida_pedem_pessoa(self):
        corrigir = Mock()
        for codigo in ("regra", "dados", "tecnico", "", None, 1):
            with self.subTest(codigo=codigo):
                resultado = executar_etapa(lambda: {"ok": False, "codigo": codigo}, corrigir, self.registrar)
                self.assertFalse(resultado["ok"])
                self.assertEqual((resultado["tentativas"], resultado["correcoes"]), (1, 0))
        corrigir.assert_not_called()

    def test_sucesso_inicial_sem_custo_e_sem_correcao(self):
        corrigir = Mock()
        resultado = executar_etapa(lambda: {"ok": True}, corrigir, self.registrar)
        self.assertTrue(resultado["ok"])
        self.assertEqual((resultado["tentativas"], resultado["correcoes"], resultado["custo_centavos"]), (1, 0, 0))
        corrigir.assert_not_called()

    def test_correcao_recusada_tem_custo_e_nao_reexecuta(self):
        tentar = Mock(return_value={"ok": False, "codigo": "implementacao"})
        corrigir = Mock(return_value={"ok": False, "custo_centavos": 5, "erro": "Modelo fora do plano"})
        resultado = executar_etapa(tentar, corrigir, self.registrar)
        self.assertEqual(resultado["codigo"], "correcao_recusada")
        self.assertEqual((resultado["custo_centavos"], resultado["correcoes"], tentar.call_count), (5, 1, 1))
        self.assertEqual([tipo for tipo, _ in self.eventos][-2:], ["fix_failed", "intervention_requested"])

    def test_erro_no_corretor_e_dados_invalidos_jamais_viram_sucesso(self):
        tentar = Mock(return_value={"ok": False, "codigo": "implementacao"})
        casos = [
            (None, False), ([], False), ({"ok": True}, False),
            ({"ok": True, "custo_centavos": -1}, False),
            ({"ok": True, "custo_centavos": False}, False),
            ({"ok": "sim", "custo_centavos": 5}, True),
            (RuntimeError("interrompido"), False),
        ]
        for retorno, custo_conhecido in casos:
            with self.subTest(retorno=retorno):
                corrigir = Mock(side_effect=retorno) if isinstance(retorno, Exception) else Mock(return_value=retorno)
                resultado = executar_etapa(tentar, corrigir, self.registrar)
                self.assertFalse(resultado["ok"])
                self.assertEqual((resultado["tentativas"], resultado["correcoes"]), (1, 1))
                self.assertEqual(resultado["custo_completo"], custo_conhecido)

    def test_limite_zero_ou_corretor_ausente_impedem_correcao(self):
        tentar = Mock(return_value={"ok": False, "codigo": "implementacao"})
        corrigir = Mock()
        self.assertEqual(executar_etapa(tentar, corrigir, self.registrar, limite=0)["codigo"], "limite_atingido")
        self.assertEqual(executar_etapa(tentar, None, self.registrar)["codigo"], "sem_corretor")
        corrigir.assert_not_called()
        for limite in (-1, 4, True, 1.5):
            with self.assertRaises(ValueError):
                executar_etapa(tentar, corrigir, self.registrar, limite=limite)

    def test_erro_ou_retorno_invalido_na_verificacao_pede_intervencao(self):
        corrigir = Mock()
        for tentar in (Mock(side_effect=ValueError), Mock(return_value={"ok": "sim"}), Mock(return_value=None)):
            resultado = executar_etapa(tentar, corrigir, self.registrar)
            self.assertEqual((resultado["ok"], resultado["codigo"], resultado["tentativas"]), (False, "tecnico", 1))
        corrigir.assert_not_called()

    def test_interrompe_se_o_registro_falhar_antes_de_corrigir(self):
        tentar = Mock(return_value={"ok": False, "codigo": "implementacao"})
        corrigir = Mock()
        with self.assertRaises(OSError):
            executar_etapa(tentar, corrigir, Mock(side_effect=OSError), limite=2)
        corrigir.assert_not_called()


if __name__ == "__main__":
    unittest.main()
