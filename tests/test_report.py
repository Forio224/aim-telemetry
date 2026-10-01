"""Тесты расчётов отчёта: python -m pytest tests"""

import unittest
from datetime import datetime, timedelta

from aim_telemetry import diagnose as dg
from aim_telemetry import report
from aim_telemetry.model import Run

T0 = datetime(2026, 9, 1, 20, 0)
NO_PROGRESS = dg.Progress(None, 0, False)


def run(hours: float, score: float = 100, scenario: str = "S") -> Run:
    return Run(T0 + timedelta(hours=hours), scenario, score, 50.0, 0, None, "трек",
               "46.65", "1600", "103", "2560x1440")


class BreakBeforeTest(unittest.TestCase):
    def test_short_pause_is_not_a_break(self):
        runs = [run(0), run(71.9)]
        self.assertIsNone(report.break_before(runs, runs[1:]))

    def test_counts_whole_days_from_last_run_of_previous_session(self):
        runs = [run(0), run(0.5), run(0.5 + 4 * 24 + 23)]   # 4 сут 23 ч
        self.assertEqual(report.break_before(runs, runs[2:]), 4)

    def test_exactly_three_days_is_a_break(self):
        runs = [run(0), run(72)]
        self.assertEqual(report.break_before(runs, runs[1:]), 3)

    def test_first_session_in_history_has_no_break(self):
        runs = [run(0), run(0.1)]
        self.assertIsNone(report.break_before(runs, runs))

    def test_older_session_counts_its_own_break(self):
        runs = [run(0), run(5 * 24), run(6 * 24)]   # --session 2: перерыв перед ней, а не после
        self.assertEqual(report.break_before(runs, runs[1:2]), 5)


class BreakHintTest(unittest.TestCase):
    def row(self, now: list[float], break_days: int | None) -> dict:
        window = [run(100 + i * 0.05, s) for i, s in enumerate(now)]
        return report.scenario_row("S", window, dg.Baseline([100.0] * 12, 101, False),
                                   NO_PROGRESS, None, break_days)

    def test_below_after_break_gets_hint_and_keeps_label(self):
        plain, after = self.row([90, 90, 90], None), self.row([90, 90, 90], 4)
        self.assertEqual(after["label"], dg.BELOW)
        self.assertEqual(after["label"], plain["label"])
        self.assertEqual(after["hints"], plain["hints"] + [["after_break", {"days": 4}]])

    def test_other_labels_get_no_break_hint(self):
        for scores in ([110, 110, 110], [100, 100.5, 99.5], [90, 110]):   # выше, потолок, мало
            row = self.row(scores, 4)
            self.assertNotIn("after_break", [code for code, _ in row["hints"]], row["label"])

    def test_table_passes_break_to_rows(self):
        window = [run(100 + i * 0.05, 90) for i in range(3)]
        table = report.scenario_table(window, window, {"S": dg.Baseline([100.0] * 12, 101, False)},
                                      None, 4)
        self.assertIn(["after_break", {"days": 4}], table[0]["hints"])


if __name__ == "__main__":
    unittest.main()
