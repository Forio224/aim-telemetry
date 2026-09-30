"""Тесты разбора csv KovaaK's: python -m pytest tests"""

import os
import tempfile
import unittest
from datetime import datetime

from aim_telemetry import kovaaks as kd

CLICK_CSV = """Kill #,Timestamp,Bot,Weapon,TTK,Shots,Hits,Accuracy,Damage Done,Damage Possible,Efficiency,Cheated,OverShots
1,23:59:56.375,Target 600 Bot,BB Gun,0.000000s,1,1,1.000000,1.000000,1.000000,1.000000,0,0
2,23:59:56.598,Target 600 Bot,BB Gun,0.000000s,2,1,0.500000,1.000000,1.000000,1.000000,0,2

Weapon,Shots,Hits,Damage Done,Damage Possible,,Sens Scale,Horiz Sens
BB Gun,4,3,3.0,4.0,

Kills:,2
Score:,241.586136
Horiz Sens:,46.650002
DPI:,1600
FOV:,103.0
Resolution:,2560x1440
"""

TRACK_CSV = """Weapon,Shots,Hits,Damage Done,Damage Possible
LG,1000,550,550.0,1000.0,

Score:,3100.5
Horiz Sens:,46.650002
"""

NAME = "1w4t shrink - Challenge - 2026.10.01-00.00.53 Stats.csv"


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name: str, text: str) -> str:
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_click_run_reads_score_accuracy_and_overshots(self):
        run = kd.parse_run(self.write(NAME, CLICK_CSV), "1w4t shrink", datetime(2026, 10, 1))
        self.assertAlmostEqual(run.score, 241.586136)
        self.assertAlmostEqual(run.accuracy, 75.0)
        self.assertEqual((run.kills, run.overshots, run.kind), (2, 2, "click"))
        self.assertEqual((run.sens, run.dpi, run.res), ("46.650002", "1600", "2560x1440"))

    def test_tracking_run_has_no_kills(self):
        run = kd.parse_run(self.write("t.csv", TRACK_CSV), "Track", datetime(2026, 10, 1))
        self.assertEqual((run.kind, run.kills), ("track", 0))
        self.assertAlmostEqual(run.accuracy, 55.0)
        self.assertEqual(run.fov, "?")

    def test_file_without_score_is_skipped(self):
        path = self.write("broken.csv", CLICK_CSV.replace("Score:,241.586136\n", ""))
        self.assertIsNone(kd.parse_run(path, "x", datetime(2026, 10, 1)))

    def test_load_runs_takes_time_from_name_and_ignores_other_files(self):
        self.write(NAME, CLICK_CSV)
        self.write("notes.txt", "не статистика")
        self.write("Track - Challenge - 2026.09.30-23.00.00 Stats.csv", TRACK_CSV)
        runs = kd.load_runs(self.tmp.name)
        self.assertEqual([r.scenario for r in runs], ["Track", "1w4t shrink"])
        self.assertEqual(runs[1].when, datetime(2026, 10, 1, 0, 0, 53))


if __name__ == "__main__":
    unittest.main()
