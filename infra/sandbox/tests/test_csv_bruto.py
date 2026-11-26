"""Leitura de CSV sem interpretação. Fixtures pequenas e sintéticas, montadas em bytes.

Rodar dentro da imagem (lxml e duckdb estão lá):
    docker run --rm --network none --read-only --tmpfs /tmp -v "$PWD/infra/sandbox:/src:ro" \
      -e PYTHONPATH=/src korda-sandbox:dev python -m unittest discover -s /src/tests -v
"""

import unittest

from korda_ingestao.csv_bruto import ErroCsv, decodificar, detectar_separador, ler_csv


class TestSeparador(unittest.TestCase):
    def test_ponto_e_virgula_com_virgula_decimal(self):
        lido = ler_csv(b"cd_ped;ps_bruto;dt_baixa\n100001;363,9;2026-09-01 08:33\n100002;270,8;01/09/26\n")
        self.assertEqual(lido.separador, ";")
        self.assertEqual(lido.colunas, ["cd_ped", "ps_bruto", "dt_baixa"])
        self.assertEqual([v for _, v in lido.linhas],
                         [["100001", "363,9", "2026-09-01 08:33"], ["100002", "270,8", "01/09/26"]])

    def test_virgula_com_decimal_entre_aspas(self):
        lido = ler_csv(b'NUM_PEDIDO,PESO,OBS\n1,"192,3",ok\n2,"379,3","a, b"\n')
        self.assertEqual(lido.separador, ",")
        self.assertEqual([v for _, v in lido.linhas], [["1", "192,3", "ok"], ["2", "379,3", "a, b"]])

    def test_pipe(self):
        lido = ler_csv(b"pedidoId|dtEntregaReal\n1|2026-07-01\n2|\n")
        self.assertEqual(lido.separador, "|")
        self.assertEqual([v for _, v in lido.linhas], [["1", "2026-07-01"], ["2", ""]])

    def test_tab(self):
        self.assertEqual(detectar_separador("a\tb\tc\n1\t2\t3\n"), "\t")


class TestCodificacao(unittest.TestCase):
    def test_utf8(self):
        self.assertEqual(decodificar("São Paulo".encode("utf-8")), ("utf-8", "São Paulo"))

    def test_bom_utf8(self):
        lido = ler_csv(b"\xef\xbb\xbfcd_cli;ds_razao\n1;Ac\xc3\xa9\n")
        self.assertEqual(lido.codificacao, "utf-8-sig")
        self.assertEqual(lido.colunas[0], "cd_cli")  # o BOM não gruda no primeiro nome

    def test_latin1_cp1252(self):
        lido = ler_csv("cidade;uf\nSão Paulo;SP\nJundiaí;SP\n".encode("cp1252"))
        self.assertEqual(lido.codificacao, "cp1252")
        self.assertEqual(lido.linhas[0][1], ["São Paulo", "SP"])

    def test_byte_fora_do_cp1252_cai_em_latin1(self):
        codificacao, texto = decodificar(b"a;b\n\x81;x\n")
        self.assertEqual(codificacao, "latin-1")
        self.assertIn("\x81", texto)


class TestCabecalho(unittest.TestCase):
    def test_sem_cabecalho_gera_nomes_posicionais(self):
        lido = ler_csv(b"1;2026-01-01;10,5\n2;2026-01-02;11,0\n")
        self.assertFalse(lido.cabecalho)
        self.assertEqual(lido.colunas, ["coluna_1", "coluna_2", "coluna_3"])
        self.assertEqual(len(lido.linhas), 2)
        self.assertEqual(lido.linhas[0][0], 1)

    def test_nomes_originais_preservados(self):
        lido = ler_csv(b"pedidoId;dtEntregaReal;NUM_PEDIDO\nx;y;z\n")
        self.assertEqual(lido.colunas, ["pedidoId", "dtEntregaReal", "NUM_PEDIDO"])

    def test_nome_repetido_ganha_sufixo_e_original_fica_no_manifesto(self):
        lido = ler_csv(b"obs;OBS;id\na;b;c\n")
        self.assertEqual(lido.colunas, ["obs", "OBS__2", "id"])
        self.assertEqual(lido.colunas_originais, ["obs", "OBS", "id"])

    def test_nome_vazio_vira_posicional(self):
        lido = ler_csv(b"a;b;\n1;2;3\n")
        self.assertEqual(lido.colunas, ["a", "b", "coluna_3"])

    def test_coluna_com_nome_da_linhagem_e_recusada(self):
        with self.assertRaises(ErroCsv):
            ler_csv(b"_arquivo;x\n1;2\n", reservados=("_arquivo", "_linha"))


class TestFidelidade(unittest.TestCase):
    def test_valores_nao_sao_limpos(self):
        lido = ler_csv(b"a;b;c\n  espaco ;;N/A\n")
        self.assertEqual(lido.linhas[0][1], ["  espaco ", "", "N/A"])

    def test_linha_malformada_vai_para_rejeitados_com_numero_da_linha(self):
        lido = ler_csv(b"a;b\n1;2\n3;4;5\n6;7\n")
        self.assertEqual([l for l, _ in lido.linhas], [2, 4])
        self.assertEqual(len(lido.rejeitados), 1)
        r = lido.rejeitados[0]
        self.assertEqual((r.linha, r.motivo, r.conteudo_bruto), (3, "campos_3_esperados_2", "3;4;5\n"))

    def test_linha_vazia_no_meio_e_registrada(self):
        lido = ler_csv(b"a;b\n1;2\n\n3;4\n")
        self.assertEqual([l for l, _ in lido.linhas], [2, 4])
        self.assertEqual([(r.linha, r.motivo) for r in lido.rejeitados], [(3, "linha_vazia")])

    def test_quebra_de_linha_entre_aspas_mantem_numero_da_linha_fisica(self):
        lido = ler_csv(b'a;b\n1;"x\ny"\n2;z\n')
        self.assertEqual(lido.linhas, [(2, ["1", "x\ny"]), (4, ["2", "z"])])

    def test_aspas_invalidas_sao_rejeitadas_e_leitura_continua(self):
        lido = ler_csv(b'a;b\n1;"x"y\n2;z\n')
        self.assertEqual(lido.linhas, [(3, ["2", "z"])])
        self.assertEqual(lido.rejeitados[0].linha, 2)
        self.assertTrue(lido.rejeitados[0].motivo.startswith("csv_invalido"))

    def test_crlf(self):
        lido = ler_csv(b"a;b\r\n1;2\r\n")
        self.assertEqual(lido.linhas, [(2, ["1", "2"])])

    def test_arquivo_vazio(self):
        lido = ler_csv(b"")
        self.assertEqual((lido.colunas, lido.linhas, lido.rejeitados), ([], [], []))


if __name__ == "__main__":
    unittest.main()
