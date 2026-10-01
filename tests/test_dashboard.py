"""Тесты сборки дашборда: python -m pytest tests"""

import json
import os
import re
import tempfile
import unittest
from datetime import datetime, timedelta

from aim_telemetry import changes as aim_changes
from aim_telemetry import dashboard as dash
from aim_telemetry.model import Run

T0 = datetime(2026, 9, 20, 20, 0)


def run(minutes: float, score: float, scenario: str = "S") -> Run:
    return Run(T0 + timedelta(minutes=minutes), scenario, score, 50.0, 0, None, "трек",
               "46.65", "1600", "103", "2560x1440")


class PayloadTest(unittest.TestCase):
    def test_days_count_runs_and_session_minutes(self):
        runs = [run(0, 1), run(10, 1), run(24 * 60, 1)]
        days = dash.days_payload(runs)
        self.assertEqual([(d["d"], d["runs"]) for d in days], [("2026-09-20", 2), ("2026-09-21", 1)])
        self.assertAlmostEqual(days[0]["minutes"], 10 + dash.RUN_MINUTES)

    def test_source_payload_has_all_sections(self):
        runs = [run(i * 2, 100 + i, "A" if i % 2 else "B") for i in range(20)]
        payload = dash.source_payload("X", runs, [], T0 + timedelta(days=1))
        self.assertEqual({s["name"] for s in payload["scenarios"]}, {"A", "B"})
        self.assertEqual(payload["session"]["n"], 20)
        self.assertNotIn("shape", payload["session"])   # форму сессии заменил вход в сценарий
        self.assertNotIn("shape14", payload)
        self.assertIsNone(payload["entry"])              # одна сессия — цены входа нет
        self.assertIsNone(payload["session"]["breakDays"])   # первая сессия — перерыва нет
        json.dumps(dash.clean(payload))   # всё сериализуется

    def test_entry_cost_over_history(self):
        runs = [run(day * 24 * 60 + i * 2, 100 if i % 3 else 95, "AB"[i // 3])
                for day in range(10) for i in range(6)]
        entry = dash.source_payload("X", runs, [], T0 + timedelta(days=11))["entry"]
        self.assertEqual(set(entry), {"cost", "low", "high", "blocks", "sessions", "scenarios"})
        self.assertLess(entry["cost"], 0)

    def test_session_after_long_break_reports_days_and_hint(self):
        history = [run(i * 2, 100) for i in range(12)]
        window = [run(5 * 24 * 60 + i * 2, 90) for i in range(3)]
        session = dash.session_payload(history + window, [])
        self.assertEqual(session["breakDays"], 4)
        self.assertIn(["after_break", {"days": 4}], session["rows"][0]["hints"])


class WriteTest(unittest.TestCase):
    def test_data_is_embedded_and_script_tag_cannot_be_closed(self):
        runs = [run(i, 100 + i, "</script><b>x") for i in range(6)]
        sources = {"k": dash.source_payload("K", runs, [], T0 + timedelta(days=1))}
        with tempfile.TemporaryDirectory() as tmp:
            out = dash.write_dashboard(sources, [aim_changes.Change(T0, "глайды")], "2026-10-13",
                                       os.path.join(tmp, "d.html"))
            with open(out, encoding="utf-8") as fh:
                html = fh.read()
        self.assertNotIn(dash.PLACEHOLDER, html)
        self.assertEqual(len(re.findall(r"</script>", html)), 2)   # только теги самой страницы
        payload = re.search(r"const DATA = (.*?);\n", html).group(1)
        self.assertEqual(json.loads(payload)["testDate"], "2026-10-13")


if __name__ == "__main__":
    unittest.main()
