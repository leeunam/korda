"""Testes da calibração com valores conferidos à mão (não recalculados pela implementação)."""

import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import calibrate as bc  # noqa: E402

FIXTURES = HERE / "fixtures"


class AnpDieselTest(unittest.TestCase):
    def setUp(self):
        self.prices = bc.parse_anp_diesel(FIXTURES / "anp_t3_21_mini.csv", bc.load_uf_names())

    def test_maps_full_state_names_with_accents_to_uf(self):
        self.assertEqual(set(self.prices), {"SP", "AC", "RO"})

    def test_reads_comma_decimal_values(self):
        # Valores copiados da fixture: "6,085833333" e "7,655".
        self.assertAlmostEqual(self.prices["SP"][2025], 6.085833333)
        self.assertAlmostEqual(self.prices["AC"][2025], 7.655)
        self.assertAlmostEqual(self.prices["SP"][2024], 5.5)

    def test_latest_year_is_the_most_recent_shared_by_all_ufs(self):
        # RO só tem 2024 na fixture, então o ano comum mais recente é 2024.
        self.assertEqual(bc.latest_year(self.prices), 2024)
        del self.prices["RO"]
        self.assertEqual(bc.latest_year(self.prices), 2025)

    def test_unknown_uf_fails_loudly(self):
        bad = FIXTURES / "anp_t3_21_mini.csv"
        with self.assertRaises(ValueError):
            bc.parse_anp_diesel(bad, {"sao paulo": "SP"})


class DistanceTest(unittest.TestCase):
    def test_sao_paulo_rio_straight_line(self):
        # Distância em linha reta São Paulo–Rio de Janeiro amplamente citada: ~357 km.
        km = bc.haversine_km(-23.5329, -46.6395, -22.9129, -43.2003)
        self.assertAlmostEqual(km, 357, delta=5)

    def test_campinas_sao_paulo_straight_line(self):
        # Campinas–São Paulo em linha reta: ~84 km (rodovia ~95 km).
        km = bc.haversine_km(-22.9053, -47.0659, -23.5329, -46.6395)
        self.assertAlmostEqual(km, 84, delta=4)

    def test_area_has_single_sede_and_excludes_it_from_distances(self):
        area = bc.load_area()
        self.assertEqual(sum(1 for r in area if r["papel"] == "sede"), 1)
        distances = bc.distances_from_sede(area)
        self.assertEqual(len(distances), len(area) - 1)
        self.assertTrue(all(d["km_linha_reta"] > 0 for d in distances))

    def test_demand_weights_sum_to_one(self):
        total = sum(float(r["peso_demanda"]) for r in bc.load_area())
        self.assertAlmostEqual(total, 1.0, places=6)


class ObtainSourceTest(unittest.TestCase):
    """Procedência: checksum divergente e fonte manual ausente não podem passar como 'ok'."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.original = bc.EXTERNAL
        bc.EXTERNAL = Path(self.tmp.name)
        self.addCleanup(setattr, bc, "EXTERNAL", self.original)

    def _source(self, sha):
        return {"id": "fake", "titulo": "t", "licenca": "l", "modo": "automatico",
                "files": [{"url": "https://example.invalid/a.csv", "dest": "a.csv", "sha256": sha}]}

    def test_matching_checksum_is_ok(self):
        (bc.EXTERNAL / "fake").mkdir()
        (bc.EXTERNAL / "fake" / "a.csv").write_bytes(b"abc")
        # sha256("abc"), valor padrão de referência do algoritmo.
        sha = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        entry = bc.obtain_source(self._source(sha), offline=True, previous={}, now="T")
        self.assertEqual(entry["status"], "ok")

    def test_different_checksum_is_divergent(self):
        (bc.EXTERNAL / "fake").mkdir()
        (bc.EXTERNAL / "fake" / "a.csv").write_bytes(b"abd")
        sha = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        entry = bc.obtain_source(self._source(sha), offline=True, previous={}, now="T")
        self.assertEqual(entry["status"], "divergente")

    def test_manual_source_ignores_stale_manifest(self):
        folder = bc.EXTERNAL / "manual"
        folder.mkdir()
        (folder / "manifest.json").write_text("{}")
        source = {"id": "manual", "titulo": "t", "licenca": "l", "modo": "manual", "files": []}
        entry = bc.obtain_source(source, offline=True, previous={}, now="T")
        self.assertEqual(entry["status"], "pendente")


class PublicarCalibracaoTest(unittest.TestCase):
    def test_falha_preserva_a_ultima_calibracao_e_registra_o_manifesto(self):
        for status in ("pendente", "divergente"):
            with self.subTest(status=status), tempfile.TemporaryDirectory(dir=bc.ROOT) as tmp:
                pasta = Path(tmp)
                output, manifest, sources = (pasta / nome for nome in ("calibration.yaml", "manifest.json", "sources.json"))
                original = b"ultima_calibracao_valida: true\n"
                output.write_bytes(original)
                sources.write_text('{"sources": [{}]}', encoding="utf-8")
                entry = {"id": "anp", "status": status, "pendencias": ["indisponivel"]}
                with patch.multiple(bc, OUTPUT=output, MANIFEST=manifest, SOURCES=sources), \
                        patch.object(bc, "obtain_source", return_value=entry), patch.object(bc, "aggregate") as aggregate:
                    self.assertEqual(bc.main(["--offline"]), 1)
                    aggregate.assert_not_called()
                self.assertEqual(output.read_bytes(), original)
                self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["fontes"][0]["status"], status)

    def test_sucesso_publica_o_agregado_validado(self):
        with tempfile.TemporaryDirectory(dir=bc.ROOT) as tmp:
            pasta = Path(tmp)
            output, manifest, sources = (pasta / nome for nome in ("calibration.yaml", "manifest.json", "sources.json"))
            output.write_text("anterior", encoding="utf-8")
            sources.write_text('{"sources": [{}]}', encoding="utf-8")
            entry = {"id": "anp", "status": "ok"}
            with patch.multiple(bc, OUTPUT=output, MANIFEST=manifest, SOURCES=sources), \
                    patch.object(bc, "obtain_source", return_value=entry), \
                    patch.object(bc, "aggregate", return_value="agregado: valido\n"):
                self.assertEqual(bc.main(["--offline"]), 0)
            self.assertEqual(output.read_text(encoding="utf-8"), "agregado: valido\n")

    def test_erro_na_agregacao_preserva_a_ultima_calibracao(self):
        with tempfile.TemporaryDirectory(dir=bc.ROOT) as tmp:
            pasta = Path(tmp)
            output, manifest, sources = (pasta / nome for nome in ("calibration.yaml", "manifest.json", "sources.json"))
            output.write_bytes(b"anterior\n")
            sources.write_text('{"sources": [{}]}', encoding="utf-8")
            with patch.multiple(bc, OUTPUT=output, MANIFEST=manifest, SOURCES=sources), \
                    patch.object(bc, "obtain_source", return_value={"id": "anp", "status": "ok"}), \
                    patch.object(bc, "aggregate", side_effect=ValueError("ANP invalida")):
                self.assertEqual(bc.main(["--offline"]), 1)
            self.assertEqual(output.read_bytes(), b"anterior\n")


if __name__ == "__main__":
    unittest.main()
