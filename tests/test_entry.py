"""Тесты цены входа в сценарий: python -m pytest tests"""

import random
import unittest
from datetime import datetime, timedelta

from aim_telemetry import entry
from aim_telemetry.changes import Change
from aim_telemetry.model import Run

T0 = datetime(2026, 9, 1, 20, 0)


def run(minutes: float, score: float, scenario: str = "A", sens: str = "46.65") -> Run:
    return Run(T0 + timedelta(minutes=minutes), scenario, score, 50.0, 0, None, "трек",
               sens, "1600", "103", "2560x1440")


def sessions(plan: list[list[tuple[str, float]]]) -> list[Run]:
    """Сессия в день: список (сценарий, результат) с шагом 2 минуты."""
    return [run(day * 24 * 60 + i * 2, score, scenario)
            for day, session in enumerate(plan) for i, (scenario, score) in enumerate(session)]


def history(n: int = 6) -> list[list[tuple[str, float]]]:
    """База по A, B, C: каждый день по два прогона каждого, результат с разбросом."""
    return [[(sc, 100 + (i + k) % 3) for sc in "ABC" for k in range(2)] for i in range(n)]


class BlocksTest(unittest.TestCase):
    def test_return_to_scenario_is_a_new_block(self):
        runs = [run(i, 100, sc) for i, sc in enumerate("AABBAA")]
        self.assertEqual([[r.scenario for r in b] for b in entry.scenario_blocks(runs)],
                         [["A", "A"], ["B", "B"], ["A", "A"]])

    def test_session_gap_splits_a_block(self):
        runs = [run(0, 100), run(2, 100), run(43, 100), run(45, 100)]
        self.assertEqual([len(b) for b in entry.scenario_blocks(runs)], [2, 2])


class LevelsTest(unittest.TestCase):
    def test_norm_uses_only_earlier_runs(self):
        runs = sessions(history() + [[("A", 100), ("A", 101)]])
        changed = runs[:-1] + [runs[-1]._replace(score=500)]
        self.assertEqual(entry.levels(runs, [])[:-1], entry.levels(changed, [])[:-1])

    def test_no_level_without_enough_history(self):
        runs = sessions([[("A", 100)] * 3, [("A", 101)], [("A", 102)]])
        found = entry.levels(runs, [])
        self.assertEqual(found[:4], [None] * 4)   # не 0σ: такие блоки пропускаются
        self.assertIsNotNone(found[4])

    def test_whole_session_shares_one_norm(self):
        runs = sessions(history() + [[("A", 100), ("A", 100)]])
        first, second = entry.levels(runs, [])[-2:]
        self.assertEqual(first, second)   # первый прогон дня не попадает в норму второго

    def test_norm_starts_after_change_when_enough(self):
        runs = sessions([[("A", 100)] * 10, [("A", 120)] * 5, [("A", 120)]])
        level = entry.levels(runs, [Change(T0 + timedelta(hours=12), "коврик")])[-1]
        self.assertAlmostEqual(level, 0.0)


class EntryCostTest(unittest.TestCase):
    def test_single_blocks_count_as_entries(self):
        runs = sessions(history() + [[("A", 100), ("B", 100), ("C", 100)]])
        last = entry.session_levels(runs, [])[-1]
        self.assertEqual((len(last.entries), len(last.others)), (3, 0))
        self.assertEqual(last.scenarios, {"A", "B", "C"})

    def test_cost_is_first_run_against_the_rest(self):
        plan = history() + [[(sc, 95 if k == 0 else 101) for sc in "ABC" for k in range(3)]
                            for _ in range(6)]
        cost = entry.entry_cost(sessions(plan), [])
        self.assertLess(cost.cost, -1)
        self.assertLess(cost.low, cost.cost)
        self.assertLess(cost.cost, cost.high)
        self.assertEqual((cost.scenarios, cost.sessions), (3, 10))   # первые два дня — без нормы

    def test_skill_growth_is_not_an_entry_cost(self):
        # всё растёт от сессии к сессии, а первый прогон не хуже остальных
        plan = [[(sc, 100 + 4 * day + k % 2) for sc in "AB" for k in range(3)] for day in range(12)]
        runs = sessions(plan)
        entries = [z for s in entry.session_levels(runs, []) for z in s.entries]
        self.assertGreater(sum(entries) / len(entries), 1)   # против прошлой нормы вход «выше»
        self.assertLess(abs(entry.entry_cost(runs, []).cost), 0.2)

    def test_continuing_after_weak_first_pulls_cost_toward_zero(self):
        # прогон = состояние блока + шум, первый ниже на TRUE; блок продолжают после
        # слабого первого. Состояние держится — «остальные» из продолженных блоков
        # ниже среднего, и оценка сжимается к нулю, а не раздувается
        true_cost, rng = -0.5, random.Random(7)
        sample = []
        for _ in range(2000):
            found = entry.SessionLevels([], [], set())
            for _ in range(5):
                state = rng.gauss(0, 0.7)
                first = state + rng.gauss(0, 1) + true_cost
                found.entries.append(first)
                if first < -0.3:
                    found.others.extend(state + rng.gauss(0, 1) for _ in range(2))
            sample.append(found)
        self.assertLess(true_cost, entry.gap(sample))
        self.assertLess(entry.gap(sample), 0)

    def test_too_few_sessions_give_nothing(self):
        self.assertIsNone(entry.entry_cost(sessions(history(3)), []))

    def test_bootstrap_is_repeatable(self):
        plan = history() + [[(sc, 97 + k) for sc in "AB" for k in range(3)] for _ in range(6)]
        runs = sessions(plan)
        self.assertEqual(entry.entry_cost(runs, []), entry.entry_cost(runs, []))


if __name__ == "__main__":
    unittest.main()
