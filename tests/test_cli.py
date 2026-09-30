"""Сквозной прогон командной строки на временной папке настроек: python -m pytest tests"""

import contextlib
import io
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

from aim_telemetry import cli, config, i18n

CSV = """Weapon,Shots,Hits,Damage Done,Damage Possible,,Sens Scale,Horiz Sens
LG,1000,{hits},{hits}.0,1000.0,

Score:,{score}
Horiz Sens:,46.65
DPI:,1600
FOV:,103.0
Resolution:,2560x1440
"""


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.stats = os.path.join(self.tmp.name, "stats")
        os.makedirs(self.stats)
        start = datetime(2026, 9, 20, 20, 0)
        # две сессии по 8 прогонов двух сценариев: есть и база, и окно
        for day in range(2):
            for i in range(8):
                when = start + timedelta(days=day, minutes=2 * i)
                name = "Track %s - Challenge - %s Stats.csv" % ("AB"[i % 2], when.strftime("%Y.%m.%d-%H.%M.%S"))
                with open(os.path.join(self.stats, name), "w", encoding="utf-8") as fh:
                    fh.write(CSV.format(hits=500 + i, score=3000 + 10 * i + 50 * day))
        self.folder = os.path.join(self.tmp.name, "cfg")
        os.makedirs(self.folder)
        config.save(config.Config(kovaaks_dir=self.stats, steam_id="1"), config.config_path(self.folder))
        self.patch = mock.patch.object(config, "config_dir", return_value=self.folder)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        i18n.set_lang("ru")
        self.tmp.cleanup()

    def run_cli(self, *argv: str) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.run(list(argv))
        return out.getvalue()

    def test_session_report_in_both_languages(self):
        ru = self.run_cli()
        self.assertIn("СЦЕНАРИИ", ru)
        self.assertIn("Track A", ru)
        en = self.run_cli("--lang", "en")
        self.assertIn("SCENARIOS", en)
        self.assertNotIn("СЦЕНАРИИ", en)

    def test_set_and_show_config(self):
        self.run_cli("--set", "test_date=2026-10-13", "lang=en")
        cfg = config.load(config.config_path(self.folder))
        self.assertEqual((cfg.test_date, cfg.lang), ("2026-10-13", "en"))
        self.assertIn("SETTINGS", self.run_cli("--config"))

    def test_dashboard_without_network(self):
        out_path = os.path.join(self.tmp.name, "d.html")
        self.run_cli("--dashboard", "--no-open", "--no-bench", "--out", out_path)
        with open(out_path, encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn('"Track A"', html)
        self.assertNotIn("/*__", html)          # все куски страницы подставлены
        self.assertIn("echarts", html)          # библиотека встроена, сеть не нужна

    def test_unknown_format_is_reported(self):
        with open(os.path.join(self.stats, "X - Challenge - 2026.09.25-10.00.00 Stats.csv"), "w") as fh:
            fh.write("garbage")
        for name in os.listdir(self.stats):
            if not name.startswith("X"):
                os.remove(os.path.join(self.stats, name))
        with self.assertRaises(SystemExit) as caught:
            self.run_cli()
        self.assertIn("не распознан", str(caught.exception.code))


if __name__ == "__main__":
    unittest.main()
