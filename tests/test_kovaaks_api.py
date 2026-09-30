"""Тесты списка бенчмарков: python -m pytest tests"""

import unittest

from aim_telemetry import kovaaks_api as api


class BenchListTest(unittest.TestCase):
    def test_parses_ids_names_and_skips_junk(self):
        lines = ["# комментарий", "", "2834  # Voltaic S5.5 Intermediate", "687", "мусор",
                 "2834  # дубль"]
        self.assertEqual(api.parse_bench_list(lines),
                         [(2834, "Voltaic S5.5 Intermediate"), (687, "бенчмарк 687")])


if __name__ == "__main__":
    unittest.main()
