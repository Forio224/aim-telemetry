"""Автопоиск по файлам Steam на поддельном дереве: python -m pytest tests"""

import os
import tempfile
import unittest

from aim_telemetry import steam

LIBRARY_VDF = r'''"libraryfolders"
{
	"0"
	{
		"path"		"%s"
		"apps" { "228980" "1" }
	}
	"1"
	{
		"path"		"%s"
	}
}'''

MANIFEST = '''"AppState"
{
	"appid"		"824270"
	"name"		"KovaaK's"
	"installdir"		"FPSAimTrainer"
}'''

LOGIN_USERS = '''"users"
{
	"111"
	{
		"PersonaName"		"Old"
		"MostRecent"		"0"
		"Timestamp"		"100"
	}
	"222"
	{
		"PersonaName"		"Player \\"One\\""
		"MostRecent"		"1"
		"Timestamp"		"50"
	}
}'''


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class VdfTest(unittest.TestCase):
    def test_nested_keys_and_escapes(self):
        data = steam.parse_vdf('"a" { "b" "C:\\\\Games" "c" { "d" "1" } }')
        self.assertEqual(data, {"a": {"b": "C:\\Games", "c": {"d": "1"}}})


class DiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "Steam")
        self.lib = os.path.join(self.tmp.name, "Library")
        vdf_path = lambda p: p.replace("\\", "\\\\")   # noqa: E731 — пути в VDF экранированы
        write(os.path.join(self.root, "steamapps", "libraryfolders.vdf"),
              LIBRARY_VDF % (vdf_path(self.root), vdf_path(self.lib)))
        write(os.path.join(self.lib, "steamapps", "appmanifest_824270.acf"), MANIFEST)
        os.makedirs(os.path.join(self.lib, "steamapps", "common", "FPSAimTrainer"))
        write(os.path.join(self.root, "config", "loginusers.vdf"), LOGIN_USERS)

    def tearDown(self):
        self.tmp.cleanup()

    def test_libraries_and_app_dir(self):
        self.assertEqual(len(steam.library_paths(self.root)), 2)
        self.assertEqual(steam.app_dir(self.root, "824270"),
                         os.path.join(self.lib, "steamapps", "common", "FPSAimTrainer"))
        self.assertIsNone(steam.app_dir(self.root, "1100990"))

    def test_most_recent_user_wins_over_timestamp(self):
        self.assertEqual(steam.last_user(self.root), steam.SteamUser("222", 'Player "One"'))

    def test_missing_files_give_nothing(self):
        empty = os.path.join(self.tmp.name, "nothing")
        self.assertEqual(steam.library_paths(empty), [])
        self.assertIsNone(steam.last_user(empty))
        self.assertIsNone(steam.process_log(empty))


if __name__ == "__main__":
    unittest.main()
