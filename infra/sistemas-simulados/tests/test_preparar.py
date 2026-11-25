"""Preparo do replay por dia. Roda na imagem (PyYAML):

    docker run --rm --network none --read-only --tmpfs /tmp --user "$(id -u):$(id -g)" \
      -v "$PWD/infra/sistemas-simulados:/src:ro" -e PYTHONPATH=/src korda-simulados:dev \
      python -m unittest discover -s /src/tests -v
"""

import csv
import json
import shutil
import tempfile
import unittest
from pathlib import Path

try:
    import yaml  # noqa: F401
    from korda_simulados.esquema import ErroEsquema
    from korda_simulados.preparar import preparar
except ImportError:  # fora da imagem, sem PyYAML
    preparar = None

from fixtures_mini import escrever


@unittest.skipIf(preparar is None, "PyYAML indisponível (rode na imagem korda-simulados)")
class TestPreparar(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.fontes, self.yaml = escrever(self.tmp)
        self.saida = self.tmp / "saida"
        self.cat = preparar(self.fontes, self.yaml, self.saida)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def dia(self, d):
        return self.saida / "dias" / d

    def test_dias_e_cadastros_no_primeiro_dia(self):
        self.assertEqual(self.cat["dias"], ["2026-09-01", "2026-09-02", "2026-09-03"])
        self.assertTrue((self.dia("2026-09-01") / "erp" / "erp_clientes.csv").is_file())
        self.assertTrue((self.dia("2026-09-01") / "tms" / "tms_veiculos.jsonl").is_file())

    def test_erp_tipado_para_o_banco(self):
        with (self.dia("2026-09-01") / "erp" / "erp_pedidos.csv").open() as f:
            linhas = list(csv.reader(f))
        self.assertEqual(linhas[0][:6], ["cd_ped", "cd_cli", "dt_emis", "dt_prev", "qt_itens", "ps_bruto"])
        self.assertEqual(linhas[1][5:8], ["363.9", "2.188", "100.00"])
        self.assertEqual(self.cat["erp"]["erp_pedidos"]["chave"], "cd_ped")
        self.assertIn(["ps_bruto", "numeric"], self.cat["erp"]["erp_pedidos"]["colunas"])

    def test_tms_json_mantem_texto_livre_e_vazio_vira_null(self):
        regs = [json.loads(l) for l in (self.dia("2026-09-03") / "tms" / "tms_entregas.jsonl").read_text().splitlines()]
        self.assertEqual([r["dt_baixa"] for r in regs], ["03/09/26", None])  # formato misto intacto
        self.assertEqual(regs[0]["atualizado_em"], "2026-09-03T23:00:00-03:00")
        viagem = json.loads((self.dia("2026-09-02") / "tms" / "tms_viagens.jsonl").read_text().splitlines()[0])
        self.assertEqual((viagem["dt_saida"], viagem["km"]), ("2026-09-02T07:48:00", 261.7))

    def test_entrega_vai_para_o_dia_da_viagem(self):
        self.assertEqual(self.cat["contagens"]["tms"]["tms_entregas"], {"2026-09-02": 1, "2026-09-03": 2})

    def test_cte_por_dia_byte_a_byte_com_duplicata_e_evento(self):
        self.assertEqual(sorted(p.name for p in (self.dia("2026-09-02") / "cte").iterdir()),
                         ["A-cte.xml", "A-cte_reenvio.xml"])
        self.assertEqual((self.dia("2026-09-03") / "cte" / "A-canc.xml").read_bytes(),
                         (self.fontes / "cte" / "A-canc.xml").read_bytes())

    def test_mudanca_de_esquema_no_ultimo_dia(self):
        self.assertEqual(self.cat["mudanca_esquema"],
                         {"sistema": "tms", "tabela": "tms_entregas", "coluna": "dt_baixa",
                          "novo_nome": "dt_baixa_v2", "a_partir_de": "2026-09-03"})

    def test_nao_le_gerador(self):
        self.assertNotIn("segredo", json.dumps(self.cat))
        self.assertFalse(any("_gerador" in p.as_posix() for p in self.saida.rglob("*")))

    def test_coluna_fora_do_yaml_e_recusada(self):
        (self.fontes / "tms" / "tms_veiculos.csv").write_text("id_veic;cor\nV01;azul\n")
        with self.assertRaises(ErroEsquema):
            preparar(self.fontes, self.yaml, self.tmp / "outra")


if __name__ == "__main__":
    unittest.main()
