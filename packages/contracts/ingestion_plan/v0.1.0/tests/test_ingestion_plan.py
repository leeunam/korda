"""Seção de ingestão do plano: exemplos válidos e cada regra recusando o que deve recusar.

python3 -m pip install -r requirements-contracts.txt
python3 -m unittest discover -s packages/contracts/ingestion_plan/v0.1.0/tests
"""

import copy
import importlib.util
import json
import unittest
from pathlib import Path

AQUI = Path(__file__).resolve().parents[1]
try:
    _spec = importlib.util.spec_from_file_location("validate_ingestion_plan", AQUI / "validate.py")
    validate = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(validate)
except ImportError:  # jsonschema ausente
    validate = None


def exemplo(nome):
    return json.loads((AQUI / "examples" / nome).read_text(encoding="utf-8"))


@unittest.skipIf(validate is None, "jsonschema indisponível (requirements-contracts.txt)")
class TestPlanoIngestao(unittest.TestCase):
    def setUp(self):
        self.p = exemplo("01_demo.json")

    def fonte(self, plano, fid):
        return next(f for f in plano["sources"] if f["id"] == fid)

    def assertRecusa(self, plano, trecho):
        erros = validate.validar(plano)
        self.assertTrue(any(trecho in e for e in erros), erros)

    def test_exemplos_validos(self):
        for nome in ("01_demo.json", "02_variacao.json"):
            with self.subTest(nome=nome):
                self.assertEqual(validate.validar(exemplo(nome)), [])

    def test_02_registra_viagens_trf_como_lacuna(self):
        p = exemplo("02_variacao.json")
        self.assertIn("lac-tms-viagens-trf", self.fonte(p, "tms")["gap_ids"])
        self.assertIsNone(p["context_ref"])

    def test_credencial_so_como_nome_de_variavel(self):
        p = copy.deepcopy(self.p)
        self.fonte(p, "erp")["credentials_env"].append("senha123")
        self.assertRecusa(p, "credentials_env")
        p = copy.deepcopy(self.p)
        self.fonte(p, "erp")["password"] = "x"
        self.assertRecusa(p, "Additional properties")

    def test_fonte_sem_evidencia_nem_lacuna(self):
        p = copy.deepcopy(self.p)
        f = self.fonte(p, "cte")
        f["evidence_ids"], f["gap_ids"] = [], []
        p["gaps"] = [g for g in p["gaps"] if g["source_id"] != "cte"]
        self.assertRecusa(p, "sem evidência nem lacuna")

    def test_volume_suposto_exige_lacuna_aberta(self):
        p = copy.deepcopy(self.p)
        self.fonte(p, "cte")["objects"][0]["expected_volume"]["basis"] = "suposicao"
        for g in p["gaps"]:
            g["state"] = "respondida"
        self.assertRecusa(p, "volume suposto")

    def test_incremental_exige_chave_e_so_com_metodo_incremental(self):
        p = copy.deepcopy(self.p)
        self.fonte(p, "tms")["incremental_key"] = None
        self.assertRecusa(p, "incremental_key")
        p = copy.deepcopy(self.p)
        self.fonte(p, "erp")["incremental_key"] = {"field": "x", "comparison": "maior_que"}
        self.assertRecusa(p, "incremental_key")

    def test_credencial_conforme_o_tipo_de_fonte(self):
        p = copy.deepcopy(self.p)
        self.fonte(p, "tms")["credentials_env"] = []
        self.assertRecusa(p, "exige credentials_env")
        p = copy.deepcopy(self.p)
        self.fonte(p, "cte")["credentials_env"] = ["KORDA_SFTP_SENHA"]
        self.assertRecusa(p, "não recebe credencial")

    def test_testes_de_aceite_obrigatorios(self):
        for tipo, fonte in (("mudanca_esquema", "tms"), ("incremental", "tms"), ("idempotencia", "cte")):
            with self.subTest(tipo=tipo):
                p = copy.deepcopy(self.p)
                p["acceptance_tests"] = [t for t in p["acceptance_tests"] if t["kind"] != tipo]
                self.assertRecusa(p, f"{fonte}: falta teste de aceite '{tipo}'")

    def test_lacuna_bloqueante_impede_pronto(self):
        p = copy.deepcopy(self.p)
        p["gaps"][0]["blocking"] = True
        self.assertRecusa(p, "lacunas bloqueantes abertas")
        p["state"] = "rascunho"
        self.assertEqual(validate.validar(p), [])

    def test_mudanca_de_esquema_sempre_escala(self):
        p = copy.deepcopy(self.p)
        self.fonte(p, "tms")["on_schema_change"] = "ignorar"
        self.assertRecusa(p, "on_schema_change")

    def test_no_maximo_tres_tentativas_de_correcao(self):
        p = copy.deepcopy(self.p)
        p["limits"]["max_correction_attempts"] = 4
        self.assertRecusa(p, "max_correction_attempts")

    def test_referencias_existentes(self):
        p = copy.deepcopy(self.p)
        self.fonte(p, "erp")["gap_ids"].append("lac-inexistente")
        self.assertRecusa(p, "lacuna inexistente")
        p = copy.deepcopy(self.p)
        p["acceptance_tests"][0]["source_ids"].append("sftp")
        self.assertRecusa(p, "fonte inexistente")


if __name__ == "__main__":
    unittest.main()
