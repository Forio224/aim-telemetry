"""Тесты energy и формы по бенчмарку: python -m pytest tests"""

import unittest
from datetime import datetime, timedelta

from aim_telemetry import bench as ab
from aim_telemetry.model import Run

NOW = datetime(2026, 10, 1, 12, 0)
MAXES = [100.0, 200.0, 300.0, 400.0]


def run(days_ago: float, score: float, scenario: str, sens: str = "46.65") -> Run:
    return Run(NOW - timedelta(days=days_ago), scenario, score, 50.0, 0, None, "трек",
               sens, "1600", "103", "2560x1440")


def bench(scenarios: dict[str, dict[str, float]]) -> dict:
    return {"categories": {
        cat: {"scenarios": {name: {"score": best * 100, "rank_maxes": MAXES}
                            for name, best in block.items()}}
        for cat, block in scenarios.items()}}


class EnergyTest(unittest.TestCase):
    def test_thresholds_and_interpolation(self):
        self.assertEqual(ab.energy(100, MAXES), 500)
        self.assertEqual(ab.energy(250, MAXES), 650)
        self.assertEqual(ab.energy(450, MAXES), 850)   # выше Master — шаг Jade→Master
        self.assertEqual(ab.energy(50, MAXES), 250)
        self.assertEqual(ab.rank_name(699), "Diamond")

    def test_harmonic_pulls_to_weakest(self):
        self.assertAlmostEqual(ab.harmonic([600, 800]), 685.714, places=2)


class LevelTest(unittest.TestCase):
    def test_level_is_rank_plus_share_to_next(self):
        self.assertEqual(ab.level(0, MAXES), 0)
        self.assertEqual(ab.level(50, MAXES), 0.5)
        self.assertEqual(ab.level(250, MAXES), 2.5)
        self.assertEqual(ab.level(500, MAXES), 5.0)

    def test_voltaic_tiers_get_energy_scale(self):
        self.assertEqual(ab.energy_levels(["Iron", "Bronze", "Silver", "Gold"]), [100, 200, 300, 400])
        self.assertEqual(ab.energy_levels(["Grandmaster", "Nova", "Astra", "Celestial"]),
                         [900, 1000, 1100, 1200])
        self.assertIsNone(ab.energy_levels(["Cinnabar", "Vermillion"]))

    def test_energy_matches_level_on_voltaic(self):
        levels = [500, 600, 700, 800]
        for score in (120, 250, 399):
            self.assertAlmostEqual(ab.energy(score, MAXES, levels), 400 + 100 * ab.level(score, MAXES))

    def test_level_name(self):
        names = ["A", "B", "C", "D"]
        self.assertEqual(ab.level_name(0.9, names), "—")
        self.assertEqual(ab.level_name(2.99, names), "B")
        self.assertEqual(ab.level_name(7.0, names), "D")

    def test_bench_info_drops_no_rank(self):
        data = {"ranks": [{"name": "No Rank", "color": "#fff"}, {"name": "Platinum", "color": "#1"},
                          {"name": "Diamond", "color": "#2"}]}
        info = ab.bench_info(1, "x", data)
        self.assertEqual(info.ranks, ["Platinum", "Diamond"])
        self.assertEqual(info.levels, [500, 600])


class FormTest(unittest.TestCase):
    def test_form_uses_recent_runs_on_current_sens(self):
        runs = ([run(20, 350, "A")] * 3 + [run(5 - i * 0.1, 250, "A") for i in range(5)]
                + [run(1, 390, "A", sens="32")])
        rows = ab.bench_rows(bench({"Cat": {"A": 350}}), runs, "46.65", NOW)
        self.assertEqual(rows[0].form, 250)
        self.assertEqual(rows[0].form_energy, 650)
        self.assertEqual(rows[0].energy, 750)
        self.assertEqual(rows[0].last_played, NOW - timedelta(days=1))   # на любой сенсе

    def test_category_states_idle_and_missing_form(self):
        runs = [run(15, 150, "A", sens="50")]
        data = bench({"Played": {"A": 150}, "Never": {"B": 250}})
        states = ab.category_states(ab.bench_rows(data, runs, "46.65", NOW), NOW)
        played, never = states
        self.assertIsNone(played.form_energy)
        self.assertEqual(played.days_idle, 15)
        self.assertIsNone(never.days_idle)
        self.assertEqual(never.energy, 650)


if __name__ == "__main__":
    unittest.main()
