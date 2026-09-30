"""Тесты чтения Aimbeast: python -m pytest tests"""

import json
import os
import struct
import tempfile
import unittest
import zlib
from datetime import date, datetime

from aim_telemetry import aimbeast as ab

DAY = date(2026, 9, 23)


def at(hh: int, mm: int, ss: int = 0) -> datetime:
    return datetime(2026, 9, 23, hh, mm, ss)


def ue_archive(payload: bytes) -> bytes:
    """Сжатый архив UE4 из одного блока — как Config.cfg."""
    packed = zlib.compress(payload)
    header = struct.pack("<IIqqq", ab.UE_TAG, 0, 0x20000, len(packed), len(payload))
    return header + struct.pack("<qq", len(packed), len(payload)) + packed


def ue_property(name: str, value: bytes) -> bytes:
    return struct.pack("<i", len(name) + 1) + name.encode() + b"\x00" + b"\x00" * 8 + value


def ue_string(text: str) -> bytes:
    raw = text.encode() + b"\x00"
    return struct.pack("<i", len(raw)) + raw


class ParseLaunchesTest(unittest.TestCase):
    def test_splits_launches_and_ends_on_last_app_line(self):
        lines = [
            '[2026-09-23 00:36:17] AppID 1100990 adding PID 1 as a tracked process '
            '"D:\\x\\Aimbeast\\Aimbeast.exe"',
            "[2026-09-23 00:36:18] AppID 1100990 adding PID 2 as a tracked process \"cef\"",
            "[2026-09-23 00:50:00] AppID 730 adding PID 3 as a tracked process \"cs2.exe\"",
            "[2026-09-23 01:23:35] Game process removed: AppID 1100990 \"shipping\"",
            '[2026-09-23 20:00:00] AppID 1100990 adding PID 4 as a tracked process '
            '"D:\\x\\Aimbeast\\Aimbeast.exe"',
        ]
        launches = ab.parse_launches(lines)
        self.assertEqual(launches, [ab.Launch(at(0, 36, 17), at(1, 23, 35)),
                                    ab.Launch(at(20, 0), at(20, 0))])


class DayStartTest(unittest.TestCase):
    def test_skips_short_launches(self):
        launches = [ab.Launch(at(14, 0), at(14, 1)), ab.Launch(at(20, 0), at(21, 0))]
        self.assertEqual(ab.day_start(DAY, launches), at(20, 0))

    def test_launch_over_midnight_starts_day_at_midnight(self):
        launches = [ab.Launch(datetime(2026, 9, 22, 23, 30), at(0, 40))]
        self.assertEqual(ab.day_start(DAY, launches), at(0, 0))

    def test_no_launch_returns_none(self):
        self.assertIsNone(ab.day_start(DAY, []))


class WarpTest(unittest.TestCase):
    def test_stretches_between_anchors(self):
        points = ab.time_points(at(0, 0), [(600.0, at(0, 15))])
        self.assertEqual(ab.warp(points, 300.0), at(0, 7, 30))

    def test_long_break_puts_runs_next_to_anchor(self):
        points = ab.time_points(at(0, 0), [(600.0, at(5, 0))])
        self.assertEqual(ab.warp(points, 300.0), at(4, 55))

    def test_extrapolates_after_last_anchor(self):
        points = ab.time_points(at(0, 0), [(600.0, at(0, 15))])
        self.assertEqual(ab.warp(points, 660.0), at(0, 16))

    def test_drops_anchor_faster_than_game_time(self):
        points = ab.time_points(at(0, 0), [(600.0, at(0, 5))])
        self.assertEqual(points, [(0.0, at(0, 0))])

    def test_without_start_backdates_from_first_anchor(self):
        points = ab.time_points(None, [(600.0, at(1, 0))])
        self.assertEqual(points[0], (0.0, at(0, 50)))


class LayOutDayTest(unittest.TestCase):
    def setUp(self):
        self.stats = {"A": {DAY: [(10.0, 50.0, 5), (12.0, 60.0, 6)]},
                      "B": {DAY: [(100.0, 40.0, 0)]},
                      "C": {DAY: [(1.0, 1.0, 1)]}}
        self.blocks = [ab.DayBlock("B", 1, 60), ab.DayBlock("A", 2, 120)]

    def test_follows_journal_order_and_appends_unknown(self):
        runs = ab.lay_out_day(DAY, self.stats, {}, self.blocks, at(10, 0))
        self.assertEqual([r.scenario for r in runs], ["B", "A", "A", "C"])
        self.assertEqual([r.when for r in runs],
                         [at(10, 1), at(10, 2), at(10, 3), at(10, 4)])
        self.assertTrue(all(r.anchored for r in runs))

    def test_mtime_of_last_day_anchors_block_end(self):
        runs = ab.lay_out_day(DAY, self.stats, {"A": at(10, 6)}, self.blocks, at(10, 0))
        self.assertEqual(runs[2].when, at(10, 6))

    def test_mtime_from_later_day_is_ignored(self):
        stats = dict(self.stats, A={DAY: self.stats["A"][DAY], date(2026, 9, 24): []})
        runs = ab.lay_out_day(DAY, stats, {"A": at(10, 6)}, self.blocks, at(10, 0))
        self.assertEqual(runs[2].when, at(10, 3))

    def test_falls_back_to_noon_without_anchors(self):
        runs = ab.lay_out_day(DAY, self.stats, {}, self.blocks, None)
        self.assertEqual(runs[0].when, at(12, 1))
        self.assertFalse(runs[0].anchored)


class FilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def write_utf16(self, rel: str, data: dict) -> None:
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-16") as fh:
            json.dump(data, fh)

    def test_load_runs_end_to_end(self):
        self.write_utf16("Statistics/Normal/CMS.json", {
            "Date": ["22/9/2026", "23/9/2026"], "Score": [1300, 1290],
            "Accuracy": [65.5, 64.4], "Kills": [0, 0]})
        self.write_utf16("Training Data/training_data_2026.json", {
            "Streak Overrides": {},
            "23/9/2026": {"CMS": {"Completed Sessions": 1, "Total Time": 60}}})
        runs = ab.load_runs(self.root, os.path.join(self.root, "missing.log"))
        self.assertEqual([r.score for r in runs], [1300.0, 1290.0])
        self.assertEqual(runs[0].when.date(), date(2026, 9, 22))

    def test_read_config_unpacks_ue_archive(self):
        blob = (b"header" + ue_property("SensivityXMainValue", struct.pack("<f", 40.0))
                + ue_property("SensitivityScale", ue_string("CM/360"))
                + ue_property("DPI", struct.pack("<f", 1600.0)))
        with open(os.path.join(self.root, "Config.cfg"), "wb") as fh:
            fh.write(ue_archive(blob))
        config = ab.read_config(self.root)
        self.assertEqual(config["SensivityXMainValue"], "40")
        self.assertEqual(config["SensitivityScale"], "CM/360")
        self.assertEqual(config["DPI"], "1600")
        self.assertNotIn("FOV", config)

    def test_read_config_rejects_foreign_file(self):
        with open(os.path.join(self.root, "Config.cfg"), "wb") as fh:
            fh.write(b"\x00" * 64)
        self.assertEqual(ab.read_config(self.root), {})


if __name__ == "__main__":
    unittest.main()
