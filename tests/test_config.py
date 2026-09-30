"""Настройки: чтение, запись, проверка значений: python -m pytest tests"""

import json
import os
import tempfile
import unittest
from unittest import mock

from aim_telemetry import config


class ConfigFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "config.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_roundtrip_and_unknown_keys_ignored(self):
        config.save(config.Config(steam_id="1", lang="en"), self.path)
        with open(self.path, encoding="utf-8") as fh:
            raw = json.load(fh)
        raw["future_key"] = "x"
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(raw, fh)
        cfg = config.load(self.path)
        self.assertEqual((cfg.steam_id, cfg.lang), ("1", "en"))

    def test_broken_file_is_treated_as_missing(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{не json")
        self.assertIsNone(config.load(self.path))

    def test_set_value_validates(self):
        cfg = config.Config()
        self.assertEqual(config.set_value(cfg, "test_date", "2026-10-13").test_date, "2026-10-13")
        self.assertEqual(cfg.test_date, "")   # исходный объект не меняется
        for key, value in (("test_date", "13.10.2026"), ("lang", "de"), ("nope", "1")):
            with self.subTest(key=key), self.assertRaises(SystemExit):
                config.set_value(cfg, key, value)


class EnsureTest(unittest.TestCase):
    def test_first_run_creates_config_and_default_files(self):
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(config.steam, "steam_root", return_value=None):
            cfg, created = config.ensure(folder, check_online=False)
            self.assertTrue(created)
            self.assertTrue(os.path.exists(config.config_path(folder)))
            with open(config.benchmarks_path(folder), encoding="utf-8") as fh:
                self.assertIn("2834", fh.read())
            _, created_again = config.ensure(folder, check_online=False)
            self.assertFalse(created_again)

    def test_discover_keeps_values_set_by_user(self):
        with mock.patch.object(config.steam, "steam_root", return_value="R"), \
                mock.patch.object(config.steam, "app_dir", return_value=None), \
                mock.patch.object(config.steam, "process_log", return_value=None), \
                mock.patch.object(config.steam, "last_user", return_value=config.steam.SteamUser("999", "X")):
            cfg = config.discover(config.Config(steam_id="111"), check_online=False)
        self.assertEqual(cfg.steam_id, "111")


if __name__ == "__main__":
    unittest.main()
