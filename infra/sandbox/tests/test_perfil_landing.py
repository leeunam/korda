"""O perfil público informa a estrutura e limita a amostra dos Parquet canônicos."""

import json
import tempfile
import unittest
from pathlib import Path

from korda_ingestao.landing import ingerir
from perfil import inspecionar


class TestPerfilLanding(unittest.TestCase):
    def test_amostra_sem_valores_e_rejeita_manifesto_divergente(self):
        with tempfile.TemporaryDirectory() as temp:
            pasta = Path(temp)
            entrada = pasta / "brutos/erp"
            entrada.mkdir(parents=True)
            linhas = ["chave;obs"] + [f"{i};{'dado-interno' if i % 2 else ''}" for i in range(110)]
            (entrada / "erp_clientes.csv").write_text("\n".join(linhas) + "\n")
            landing = pasta / "landing"
            manifesto = ingerir(entrada.parent, landing)
            perfil = inspecionar(landing, "erp_clientes")
            self.assertEqual(perfil["formato"], "parquet")
            self.assertEqual(perfil["registros_analisados"], 100)
            self.assertEqual(perfil["linhas_declaradas"], 110)
            self.assertTrue(perfil["amostra_parcial"])
            self.assertEqual(perfil["nulos_na_amostra"]["obs"], 50)
            self.assertNotIn("dado-interno", json.dumps(perfil))
            manifesto["tabelas"]["erp/erp_clientes"]["arquivo"] = "cte/cte.parquet"
            (landing / "manifesto.json").write_text(json.dumps(manifesto))
            with self.assertRaisesRegex(ValueError, "divergente"):
                inspecionar(landing, "erp_clientes")
