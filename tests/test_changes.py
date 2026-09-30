"""Тесты журнала изменений: python -m pytest tests"""

import unittest
from datetime import datetime, timedelta

from aim_telemetry import changes as ch
from aim_telemetry.model import Run

T0 = datetime(2026, 9, 10, 20, 0)


def run(day: float, score: float, scenario: str = "S", sens: str = "46.65") -> Run:
    return Run(T0 + timedelta(days=day), scenario, score, 50.0, 0, None, "трек",
               sens, "1600", "103", "2560x1440")


class ParseTest(unittest.TestCase):
    def test_parses_dates_times_and_merges_same_moment(self):
        changes = ch.parse_changes([
            "# комментарий",
            "",
            "2026-09-21  глайды",
            "2026-09-21  кронштейн",
            "2026-09-23 18:30 коврик",
            "мусорная строка",
            "2026-13-40  несуществующая дата",
        ])
        self.assertEqual(changes, [
            ch.Change(datetime(2026, 9, 21), "глайды · кронштейн"),
            ch.Change(datetime(2026, 9, 23, 18, 30), "коврик"),
        ])

    def test_last_change(self):
        changes = [ch.Change(datetime(2026, 9, 21), "a"), ch.Change(datetime(2026, 9, 23), "b")]
        self.assertEqual(ch.last_change(changes, datetime(2026, 9, 22)).text, "a")
        self.assertIsNone(ch.last_change(changes, datetime(2026, 9, 1)))


class ShiftTest(unittest.TestCase):
    def test_boundary_shift_start_and_end(self):
        changes = [ch.Change(T0 + timedelta(days=5), "глайды")]
        before = [run(i * 0.5, 100) for i in range(8)]                      # до границы
        after = [run(5 + i * 0.5, 90 if i < 5 else 110) for i in range(10)]  # просадка, потом рост
        shifts = ch.boundary_shifts(before + after, changes, 0)
        self.assertEqual(len(shifts), 1)
        self.assertAlmostEqual(shifts[0].start, -0.10)
        self.assertAlmostEqual(shifts[0].end, 0.10)

    def test_needs_runs_on_both_sides(self):
        changes = [ch.Change(T0 + timedelta(days=5), "x")]
        runs = [run(1, 100), run(2, 100)] + [run(6 + i, 100) for i in range(5)]
        self.assertEqual(ch.boundary_shifts(runs, changes, 0), [])

    def test_lookback_and_previous_change_limit_before_side(self):
        changes = [ch.Change(T0 + timedelta(days=2), "a"), ch.Change(T0 + timedelta(days=4), "b")]
        runs = ([run(0.1 * i, 50) for i in range(5)]           # до первой границы — не в «до» для b
                + [run(2 + 0.3 * i, 100) for i in range(5)]
                + [run(4 + 0.3 * i, 100) for i in range(5)])
        shifts = ch.boundary_shifts(runs, changes, 1)
        self.assertEqual(shifts[0].before, 100)
        self.assertEqual(shifts[0].runs_before, 5)

    def test_odd_sens_runs_dropped_by_dominant_sens(self):
        runs = [run(0, 100), run(1, 100), run(2, 100), run(3, 999, sens="32")]
        self.assertEqual(len(ch.dominant_sens(runs)), 3)


if __name__ == "__main__":
    unittest.main()
