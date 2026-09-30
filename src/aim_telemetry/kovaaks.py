"""Чтение файлов статистики KovaaK's: по csv на прогон в папке stats.

Формат файлов не документирован: если KovaaK's его поменяет, scan() вернёт
число файлов с правильным именем, которые не удалось разобрать, и программа
скажет «формат не распознан» вместо тихого пустого отчёта.
"""

import os
import re
from datetime import datetime

from .model import Run

APP_ID = "824270"
STATS_SUBDIR = ("FPSAimTrainer", "stats")   # внутри папки игры

NAME_RE = re.compile(r"^(.*) - Challenge - (\d{4}\.\d{2}\.\d{2}-\d{2}\.\d{2}\.\d{2}) Stats\.csv$")


def parse_kv(lines: list[str]) -> dict[str, str]:
    """Строки вида `Ключ:,значение` в конце файла."""
    out = {}
    for line in lines:
        if ":," in line:
            key, _, value = line.partition(":,")
            out[key.strip()] = value.strip()
    return out


def parse_totals(lines: list[str]) -> float | None:
    """Итоговая строка под заголовком `Weapon,Shots,Hits,...` — выстрелы и попадания.

    Для кликовых сценариев это выстрелы мышью, для трекинга — тики времени
    на цели, поэтому accuracy трекинга читается как «доля времени на цели».
    """
    for i, line in enumerate(lines):
        if i > 0 and lines[i - 1].startswith("Weapon,Shots,Hits"):
            parts = line.split(",")
            if len(parts) > 2 and parts[1].isdigit() and int(parts[1]) > 0:
                shots, hits = int(parts[1]), int(parts[2])
                return 100.0 * hits / shots
    return None


def parse_kills(lines: list[str]) -> tuple[int, int]:
    """Строки убийств. Их нет у трекинговых сценариев — по этому и различаем тип."""
    kills, overshots = 0, 0
    for line in lines:
        if not line or not line[0].isdigit():
            continue
        parts = line.split(",")
        if len(parts) < 13 or not parts[0].isdigit():
            continue
        kills += 1
        if parts[12].strip().isdigit():
            overshots += int(parts[12])
    return kills, overshots


def parse_run(path: str, scenario: str, when: datetime) -> Run | None:
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return None

    accuracy = parse_totals(lines)
    kv = parse_kv(lines)
    if accuracy is None or "Score" not in kv:
        return None
    try:
        score = float(kv["Score"])
    except ValueError:
        return None

    kills, overshots = parse_kills(lines)
    return Run(
        when=when,
        scenario=scenario,
        score=score,
        accuracy=accuracy,
        kills=kills,
        overshots=overshots,
        kind="click" if kills else "track",
        sens=kv.get("Horiz Sens", "?"),
        dpi=kv.get("DPI", "?"),
        fov=kv.get("FOV", "?"),
        res=kv.get("Resolution", "?"),
    )


def scan(stats_dir: str) -> tuple[list[Run], int]:
    """Прогоны и число файлов статистики, которые не удалось разобрать."""
    runs, skipped = [], 0
    for fname in os.listdir(stats_dir):
        m = NAME_RE.match(fname)
        if not m:
            continue
        try:
            when = datetime.strptime(m.group(2), "%Y.%m.%d-%H.%M.%S")
        except ValueError:
            skipped += 1
            continue
        run = parse_run(os.path.join(stats_dir, fname), m.group(1), when)
        if run:
            runs.append(run)
        else:
            skipped += 1
    return sorted(runs, key=lambda r: r.when), skipped


def load_runs(stats_dir: str) -> list[Run]:
    return scan(stats_dir)[0]
