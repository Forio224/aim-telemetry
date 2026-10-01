"""Каталог текстов полон и согласован: python -m pytest tests"""

import re
import unittest
from pathlib import Path

from aim_telemetry import i18n
from aim_telemetry.messages import MESSAGES, WORDS

PKG = Path(__file__).resolve().parents[1] / "src" / "aim_telemetry"
PY_KEY = re.compile(r"""\bt\(\s*"([a-z_]+\.[a-z_0-9.]+)\"""")
JS_KEY = re.compile(r"""\bT\(\s*"([a-z_]+\.[a-z_0-9.]+)\"""")
HTML_KEY = re.compile(r'data-i18n(?:-ph|-aria)?="([a-z_.0-9]+)"')
# ключи, которые код собирает из префикса и кода: label.<код> и т. п.
DYNAMIC = {
    "label": ["no_base", "above", "below", "noise", "few", "unstable", "ceiling", "plateau", "even"],
    "hint": ["no_base", "above", "below", "noise_more", "noise_never", "few", "unstable", "ceiling", "plateau"],
    "todo": ["below", "unstable", "ceiling", "plateau", "even"],
    "note": ["never", "other_sens", "form_below", "stale"],
    "legend": ["norm", "max", "spread", "acc", "over", "trend", "since_best",
               "shift", "noise", "unstable", "ceiling", "plateau", "entry"],
    "ui": ["aimbeast_note"],
}
PARAM = re.compile(r"\{(\w+)(?::\w+)?\}")


def used_keys() -> set[str]:
    keys = set()
    for path in PKG.glob("*.py"):
        keys |= set(PY_KEY.findall(path.read_text(encoding="utf-8")))
    keys |= set(JS_KEY.findall((PKG / "web" / "dashboard.js").read_text(encoding="utf-8")))
    keys |= set(HTML_KEY.findall((PKG / "web" / "template.html").read_text(encoding="utf-8")))
    keys |= {"%s.%s" % (prefix, code) for prefix, codes in DYNAMIC.items() for code in codes}
    return keys


class CatalogTest(unittest.TestCase):
    def test_every_used_key_exists_in_both_languages(self):
        missing = sorted(k for k in used_keys() if k not in MESSAGES)
        self.assertEqual(missing, [])
        untranslated = sorted(k for k, v in MESSAGES.items() if set(v) != set(i18n.LANGS))
        self.assertEqual(untranslated, [])

    def test_placeholders_match_between_languages(self):
        for key, entry in MESSAGES.items():
            with self.subTest(key=key):
                self.assertEqual(sorted(set(PARAM.findall(entry["ru"]))), sorted(set(PARAM.findall(entry["en"]))))

    def test_plural_words_exist_in_both_languages(self):
        for key, entry in WORDS.items():
            self.assertEqual(len(entry["ru"]), 3, key)
            self.assertEqual(len(entry["en"]), 2, key)


class RenderTest(unittest.TestCase):
    def tearDown(self):
        i18n.set_lang("ru")

    def test_plural_substitution(self):
        self.assertEqual(i18n.t("common.runs", n=5), "5 прогонов")
        self.assertEqual(i18n.t("common.runs", lang="en", n=1), "1 run")

    def test_switching_language(self):
        i18n.set_lang("en")
        self.assertEqual(i18n.t("label.below"), "below norm")
        i18n.set_lang("xx")   # неизвестный — русский
        self.assertEqual(i18n.t("label.below"), "ниже нормы")

    def test_unknown_key_is_visible(self):
        self.assertEqual(i18n.t("no.such.key"), "no.such.key")


if __name__ == "__main__":
    unittest.main()
