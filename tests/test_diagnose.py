"""Тесты нормы и диагноза: python -m pytest tests"""

import unittest
from datetime import datetime, timedelta

from aim_telemetry import diagnose as dg
from aim_telemetry.i18n import word
from aim_telemetry.model import Run

T0 = datetime(2026, 9, 1, 20, 0)


def run(day: float, score: float, scenario: str = "S", sens: str = "46.65") -> Run:
    return Run(T0 + timedelta(days=day), scenario, score, 50.0, 0, None, "трек",
               sens, "1600", "103", "2560x1440")


def base(scores: list[float], best: float | None = None) -> dg.Baseline:
    return dg.Baseline(scores, best if best is not None else max(scores), False)


class BuildBaselinesTest(unittest.TestCase):
    def test_takes_only_runs_before_window_on_same_sens(self):
        history = [run(i, 100 + i) for i in range(20)] + [run(3, 999, sens="50")]
        window = [run(21, 120), run(21.01, 121)]
        later = [run(30, 500)]   # после окна — не в базе, даже для --session 2
        baselines, excluded = dg.build_baselines(history + window + later, window, None)
        self.assertEqual(baselines["S"].scores, [100 + i for i in range(8, 20)])
        self.assertEqual(baselines["S"].best, 119)
        self.assertEqual(excluded, {"S": 1})

    def test_uses_only_runs_after_change_when_enough(self):
        history = [run(i, 100) for i in range(10)] + [run(10 + i, 200) for i in range(5)]
        window = [run(20, 200)]
        baselines, _ = dg.build_baselines(history + window, window, T0 + timedelta(days=10))
        self.assertEqual(baselines["S"].scores, [200] * 5)
        self.assertTrue(baselines["S"].since_change)

    def test_falls_back_to_full_history_when_little_after_change(self):
        history = [run(i, 100) for i in range(10)] + [run(10, 200)]
        window = [run(20, 200)]
        baselines, _ = dg.build_baselines(history + window, window, T0 + timedelta(days=10))
        self.assertFalse(baselines["S"].since_change)
        self.assertEqual(len(baselines["S"].scores), 11)


class DiagnoseTest(unittest.TestCase):
    def test_no_base(self):
        self.assertEqual(dg.diagnose([100], base([100, 101])).label, dg.NO_BASE)

    def test_significant_drop(self):
        verdict = dg.diagnose([90, 91, 89, 90], base([100, 101, 99, 100, 102, 98]))
        self.assertEqual(verdict.label, dg.BELOW)

    def test_shift_inside_noise_says_how_many_runs(self):
        noisy = [80, 120, 90, 110, 85, 115] * 2
        verdict = dg.diagnose([112], base(noisy))
        self.assertEqual(verdict.label, dg.NOISE)
        self.assertEqual(verdict.hint, "noise_more")
        self.assertGreater(verdict.params["n"], 0)

    def test_two_runs_are_not_judged_as_even(self):
        verdict = dg.diagnose([100, 101], base([100, 101, 99, 100, 102, 98]))
        self.assertEqual(verdict.label, dg.FEW)

    def test_ceiling(self):
        verdict = dg.diagnose([100, 100.5, 99.8], base([99, 100, 101, 100, 99, 100], best=101))
        self.assertEqual(verdict.label, dg.CEILING)

    def test_instability(self):
        verdict = dg.diagnose([88, 112, 95, 105], base([100, 101, 99, 100, 102, 98]))
        self.assertEqual(verdict.label, dg.UNSTABLE)


class NoiseMathTest(unittest.TestCase):
    def test_runs_needed_shrinks_noise_below_shift(self):
        need = dg.runs_needed(0.05, 0.05, 12)
        self.assertLess(dg.noise_limit(0.05, need, 12), 0.05)
        self.assertGreaterEqual(dg.noise_limit(0.05, need - 1, 12), 0.05)

    def test_runs_needed_none_when_base_too_short(self):
        self.assertIsNone(dg.runs_needed(0.03, 0.10, 4))


class ProgressTest(unittest.TestCase):
    def test_plateau_when_flat_and_playing(self):
        runs = [run(0, 150)] + [run(d, 140) for d in range(5, 20)]
        prog = dg.progress(runs, runs[-1].when)
        self.assertEqual(prog.days_since_best, 19)
        self.assertTrue(prog.plateau)

    def test_rising_after_old_record_is_not_plateau(self):
        runs = [run(0, 200)] + [run(d, 100 + 3 * d) for d in range(10, 25)]
        prog = dg.progress(runs, runs[-1].when)
        self.assertGreater(prog.trend, dg.PLATEAU_TREND)
        self.assertFalse(prog.plateau)

    def test_trend_needs_several_days(self):
        runs = [run(0.001 * i, 100 + i) for i in range(10)]
        self.assertIsNone(dg.trend_per_week(runs, runs[-1].when))


class PluralTest(unittest.TestCase):
    def test_russian_and_english_forms(self):
        self.assertEqual([word("run", n, "ru") for n in (1, 2, 5, 11, 12, 21, 22, 25)],
                         ["прогон", "прогона", "прогонов", "прогонов", "прогонов",
                          "прогон", "прогона", "прогонов"])
        self.assertEqual([word("run", n, "en") for n in (1, 2, 21)], ["run", "runs", "runs"])


if __name__ == "__main__":
    unittest.main()
