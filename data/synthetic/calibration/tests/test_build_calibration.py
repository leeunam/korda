"""Testes da calibração com valores conferidos à mão (não recalculados pela implementação)."""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import build_calibration as bc  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
