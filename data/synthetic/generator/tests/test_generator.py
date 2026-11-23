"""Gerador: determinismo, faixas de anomalia, XSD e funções com valores à mão."""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

GEN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GEN))

import config  # noqa: E402
import cte_xml  # noqa: E402
import generate  # noqa: E402
from anomalies import build_ctes  # noqa: E402
from model import simulate  # noqa: E402
import validate_xsd  # noqa: E402
from model import cnpj_ficticio  # noqa: E402


def cnpj_valido(cnpj: str) -> bool:
    """Validador padrão de CNPJ, escrito à parte para conferir que os fictícios são inválidos."""
    def dv(nums, pesos):
        r = sum(a * b for a, b in zip(nums, pesos)) % 11
        return 0 if r < 2 else 11 - r
    n = [int(c) for c in cnpj]
    p1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    return dv(n[:12], p1) == n[12] and dv(n[:13], [6] + p1) == n[13]


def hashes(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


class FuncoesTest(unittest.TestCase):
    def test_dv_mod11(self):
        # só o último dígito "1" com peso 2: soma 2, resto 2 -> 11-2 = 9
        self.assertEqual(cte_xml.dv_mod11("0" * 42 + "1"), 9)
        # soma múltipla de 11 -> 0
        self.assertEqual(cte_xml.dv_mod11("0" * 43), 0)

    def test_cnpj_ficticio_tem_dv_invalido(self):
        for base in ("11222333", "22333444", "33444555", "12345678"):
            cnpj = cnpj_ficticio(base)
            self.assertEqual(len(cnpj), 14)
            self.assertFalse(cnpj_valido(cnpj))

    def test_validador_reconhece_cnpj_valido(self):
        self.assertTrue(cnpj_valido("11222333000181"))  # exemplo clássico de CNPJ válido

    def test_dias_uteis(self):
        import datetime as dt
        sexta = dt.date(2026, 7, 10)
        self.assertEqual(config.add_business_days(sexta, 1, sabado=False), dt.date(2026, 7, 13))
        self.assertEqual(config.add_business_days(sexta, 1, sabado=True), dt.date(2026, 7, 11))
        self.assertEqual(config.sub_business_days(dt.date(2026, 7, 13), 1, sabado=False), sexta)


class GeracaoTest(unittest.TestCase):
    """Usa a 02 (a menor) em pasta temporária."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.a, cls.b = root / "a", root / "b"
        cls.contagens = generate.generate("02_variacao", cls.a)
        generate.generate("02_variacao", cls.b)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_mesma_semente_gera_bytes_identicos(self):
        self.assertEqual(hashes(self.a / "02_variacao"), hashes(self.b / "02_variacao"))

    def test_taxas_sorteadas_dentro_das_faixas(self):
        cfg = config.load("02_variacao").cfg
        for chave, faixa in cfg["anomalias"].items():
            if isinstance(faixa, dict):
                taxa = self.contagens["taxas_efetivas_sorteadas"][chave] * 100
                self.assertGreaterEqual(taxa, faixa["min"], chave)
                self.assertLessEqual(taxa, faixa["max"], chave)

    def test_todos_os_xml_passam_no_xsd(self):
        n, erros = validate_xsd.validate_dir(self.a / "02_variacao" / "cte")
        self.assertGreater(n, 0)
        self.assertEqual(erros, [])

    def test_nomes_de_coluna_da_empresa(self):
        cabecalho = (self.a / "02_variacao" / "tms" / "tms_entregas.csv").read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(cabecalho.split(",")[5], "DATA_ENTR")

    def test_contagens_registradas(self):
        dados = json.loads((self.a / "02_variacao" / "_gerador" / "contagens.json").read_text(encoding="utf-8"))
        self.assertGreater(dados["anomalias"]["viagem_transferencia"], 0)
        self.assertGreater(dados["ctes"]["xml_evento_cancelamento"], 0)


class TaxaZeroTest(unittest.TestCase):
    def _ctes(self, caso_ativo):
        ctx = config.load("01_demo")
        ctx.cfg["caso_explicavel"]["ativo"] = caso_ativo
        for faixa in ctx.cfg["anomalias"].values():
            if isinstance(faixa, dict):
                faixa.update(min=0, max=0)
        mundo = simulate(ctx)
        registro = []
        return build_ctes(mundo, registro), registro

    def test_zero_sem_caso_fixo_nao_planta_cancelamento_ou_duplicata(self):
        ctes, registro = self._ctes(False)
        self.assertTrue(ctes)
        self.assertFalse(any(c.cancelado or c.duplicado for c in ctes))
        self.assertFalse(any(r["tipo"] in ("cte_cancelado", "cte_duplicado") for r in registro))

    def test_zero_preserva_apenas_as_anomalias_do_caso_fixo(self):
        ctes, _ = self._ctes(True)
        cancelados = [c for c in ctes if c.cancelado]
        duplicados = [c for c in ctes if c.duplicado]
        self.assertEqual(len(cancelados), 1)
        self.assertEqual(len(duplicados), 1)
        self.assertEqual(cancelados[0].caso_explicavel, "cancelado_reemitido")
        self.assertEqual(duplicados[0].caso_explicavel, "dois_pedidos")


if __name__ == "__main__":
    unittest.main()
