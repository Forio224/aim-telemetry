"""Бенчмарк по клику считается в браузере тем же разбором, что bench.py: python -m pytest tests

Сверка гоняет web/bench_live.js через node на тех же данных и сравнивает с
bench_payload до четвёртого знака. Нет node — тест пропускается.
"""

import json
import shutil
import subprocess
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from aim_telemetry import dashboard as dash
from aim_telemetry.model import Run

WEB = Path(__file__).resolve().parents[1] / "src" / "aim_telemetry" / "web"
NOW = datetime(2026, 10, 1, 21, 0)
SENS = "46.65"


def run(days_ago: float, score: float, scenario: str, sens: str = SENS) -> Run:
    return Run(NOW - timedelta(days=days_ago), scenario, score, 50.0, 0, None, "трек",
               sens, "1600", "103", "2560x1440")


def history() -> list[Run]:
    runs = []
    for day in range(20, 0, -1):   # рост ~1%/день: тренд считается
        runs += [run(day, 100 * (1 + (20 - day) / 100), "A"), run(day - 0.01, 200 + day % 3, "B")]
    runs += [run(30, 400, "C", "40.0")]           # только на другой сенсе: формы нет
    runs += [run(25, 90, "A", "40.0")]            # старый прогон на другой сенсе не в форме
    runs += [run(12 + i / 100, 70 + i, "D") for i in range(3)]   # категория без игры 12 дней
    return sorted(runs, key=lambda r: r.when)


def bench(ranks: list[str]) -> dict:
    return {
        "benchmark_progress": 42, "overall_rank": 2,
        "ranks": [{"name": "No Rank", "color": ""}] + [{"name": n, "color": "#11aa22"} for n in ranks],
        "categories": {
            "Clicking ": {"category_rank": 2, "scenarios": {
                "A": {"score": 12500, "rank_maxes": [90, 105, 120, 135]}}},   # форма ниже рекорда
            "Other sens": {"category_rank": 3, "scenarios": {
                "C": {"score": 40000, "rank_maxes": [300, 350, 420, 500]}}},
            "Tracking": {"category_rank": 1, "scenarios": {
                "B": {"score": 20500, "rank_maxes": [180, 210, 240, 270]},
                "Never Played": {"score": 0, "rank_maxes": [50, 60, 70, 80]}}},
            "Stability": {"category_rank": 0, "scenarios": {   # не играна ни разу
                "E": {"score": 0, "rank_maxes": [10, 20, 30, 40]}}},
            "Old": {"category_rank": 1, "scenarios": {
                "D": {"score": 7200, "rank_maxes": [60, 80, 100, 120]}}},
        },
    }


def close(test: unittest.TestCase, js, py, path: str = "") -> None:
    if isinstance(py, float) or isinstance(js, float):
        test.assertAlmostEqual(js, py, places=3, msg=path)
    elif isinstance(py, dict):
        test.assertEqual(sorted(js), sorted(py), path)
        for key in py:
            close(test, js[key], py[key], path + "." + key)
    elif isinstance(py, list):
        test.assertEqual(len(js), len(py), path)
        for i, (a, b) in enumerate(zip(js, py)):
            close(test, a, b, "%s[%d]" % (path, i))
    else:
        test.assertEqual(js, py, path)


@unittest.skipUnless(shutil.which("node"), "node не установлен")
class LiveBenchParityTest(unittest.TestCase):
    def analyze_js(self, bench_id: int, name: str, data: dict, runs: list[Run]) -> dict:
        scenarios, sens_list = dash.scenarios_payload(runs, NOW)
        args = [bench_id, name, data, dash.clean(scenarios), sens_list, runs[-1].sens, dash.ts(NOW)]
        script = (WEB / "bench_live.js").read_text(encoding="utf-8") + (
            "\nconst a = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
            "\nprocess.stdout.write(JSON.stringify(BENCH.analyze(...a)));")
        done = subprocess.run(["node", "-e", script], input=json.dumps(args), capture_output=True,
                              text=True, encoding="utf-8", check=True)
        return dash.clean(json.loads(done.stdout))

    def check(self, ranks: list[str]) -> None:
        runs, data = history(), bench(ranks)
        py = dash.clean(dash.bench_payload(7, "Test", data, runs, NOW))
        close(self, self.analyze_js(7, "Test", data, runs), json.loads(json.dumps(py)))

    def test_voltaic_energy_matches_python(self):
        self.check(["Platinum", "Diamond", "Jade", "Master"])

    def test_rank_levels_match_python(self):
        self.check(["Bronze", "Silver", "Gold", "Elite"])

    def test_fixture_covers_every_note(self):
        notes = dash.bench_payload(7, "Test", bench(["Bronze", "Silver", "Gold", "Elite"]), history(), NOW)["notes"]
        self.assertEqual({code for _, code, _ in notes}, {"never", "other_sens", "form_below", "stale"})

    def test_empty_answer_is_rejected(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.analyze_js(7, "Test", {"categories": {}}, history())


if __name__ == "__main__":
    unittest.main()
