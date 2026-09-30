"""Журнал изменений (железо, посадка, сенса) и сравнение периодов между ними.

Файл `changes.txt` в папке настроек, по строке на изменение:

    # дата [время]   что изменилось
    2026-09-21       стеклянные глайды · локоть на столе
    2026-09-23 18:00 коврик вернул к краю стола

Изменения с одним временем сливаются в одну границу — развести их нельзя.

Для каждой границы по каждому сценарию сравниваются три точки: «до» — медиана
последних прогонов перед границей, «сразу» — первых после неё, «к концу» —
последних в новом периоде. «Сразу» почти не загрязнено тренировкой и
показывает цену перестройки; «к концу» включает и адаптацию, и общий рост.
"""

import os
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import NamedTuple

from .i18n import t
from .model import Run, median, spread

POINT_RUNS = 5          # сколько прогонов в каждой точке «до / сразу / к концу»
MIN_SIDE_RUNS = 3       # меньше с любой стороны — сценарий в сравнение не идёт
LOOKBACK = timedelta(days=21)   # «до» ищем не дальше трёх недель от границы
SHOW_ROWS = 12          # сколько сценариев показывать под каждой границей

LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[ T](\d{1,2}:\d{2}))?\s+(.+)$")


class Change(NamedTuple):
    when: datetime
    text: str


class Shift(NamedTuple):
    """Сдвиг одного сценария на границе, в долях «до»."""

    scenario: str
    before: float
    start: float          # доля: -0.03 = сразу на 3% ниже
    end: float | None     # None — в новом периоде мало прогонов для «к концу»
    z_start: float        # тот же сдвиг в единицах разброса сценария
    runs_before: int
    runs_after: int


# ── журнал ───────────────────────────────────────────────────────────────────

def parse_changes(lines: list[str]) -> list[Change]:
    merged = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = LINE_RE.match(line)
        if not m:
            continue
        try:
            when = datetime.strptime("%s %s" % (m.group(1), m.group(2) or "00:00"),
                                     "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        merged.setdefault(when, []).append(m.group(3).strip())
    return [Change(when, " · ".join(texts)) for when, texts in sorted(merged.items())]


def load_changes(path: str) -> list[Change]:
    try:
        with open(path, encoding="utf-8") as fh:
            return parse_changes(fh.read().splitlines())
    except OSError:
        return []


def last_change(changes: list[Change], moment: datetime) -> Change | None:
    """Последнее изменение не позже момента."""
    past = [c for c in changes if c.when <= moment]
    return past[-1] if past else None


# ── сравнение периодов ───────────────────────────────────────────────────────

def dominant_sens(runs: list[Run]) -> list[Run]:
    """Прогоны на самой частой сенсе стороны — случайные прогоны на чужой отбрасываем."""
    if not runs:
        return runs
    sens = Counter(r.sens for r in runs).most_common(1)[0][0]
    return [r for r in runs if r.sens == sens]


def scenario_shift(scenario: str, before: list[Run], after: list[Run]) -> Shift | None:
    before, after = dominant_sens(before), dominant_sens(after)
    if len(before) < MIN_SIDE_RUNS or len(after) < MIN_SIDE_RUNS:
        return None
    base_scores = [r.score for r in before[-POINT_RUNS:]]
    base = median(base_scores)
    if not base:
        return None
    start = median([r.score for r in after[:POINT_RUNS]])
    end = (median([r.score for r in after[-POINT_RUNS:]])
           if len(after) >= 2 * POINT_RUNS else None)
    rel_start = (start - base) / base
    return Shift(scenario, base, rel_start,
                 (end - base) / base if end is not None else None,
                 rel_start / spread([r.score for r in before]), len(before), len(after))


def boundary_shifts(runs: list[Run], changes: list[Change], index: int) -> list[Shift]:
    """Сдвиги всех сценариев на границе changes[index]."""
    edge = changes[index].when
    since = max(edge - LOOKBACK, changes[index - 1].when if index else datetime.min)
    until = changes[index + 1].when if index + 1 < len(changes) else datetime.max
    sides = {}
    for run in runs:
        if since <= run.when < edge:
            sides.setdefault(run.scenario, ([], []))[0].append(run)
        elif edge <= run.when < until:
            sides.setdefault(run.scenario, ([], []))[1].append(run)
    shifts = [scenario_shift(name, before, after) for name, (before, after) in sides.items()]
    return [s for s in shifts if s]


# ── вывод ────────────────────────────────────────────────────────────────────

def fmt_share(value: float | None) -> str:
    return "%+6.1f%%" % (value * 100) if value is not None else "      —"


def print_boundary(change: Change, shifts: list[Shift]) -> None:
    print("%s  %s" % (change.when.strftime("%d.%m.%y"), change.text))
    if not shifts:
        print("  " + t("changes.none", n=MIN_SIDE_RUNS))
        print()
        return
    ends = [s.end for s in shifts if s.end is not None]
    late = (t("changes.late", pct=fmt_share(median(ends)).strip(), n=len(ends)) if ends
            else t("changes.late_none"))
    print("  " + t("changes.summary", n=len(shifts), pct=fmt_share(median([s.start for s in shifts])).strip(),
                   z="%+.1f" % median([s.z_start for s in shifts]), late=late))
    print("  %-32s %9s %8s %8s %6s %9s" % (
        t("col.scenario"), t("col.before"), t("col.start"), t("col.end"), "σ", t("col.runs_ba")))
    ordered = sorted(shifts, key=lambda s: -(s.runs_before + s.runs_after))[:SHOW_ROWS]
    for s in sorted(ordered, key=lambda s: s.start):
        print("  %-32s %9.1f %s %s %+6.1f %4d/%-4d" % (
            s.scenario[:32], s.before, fmt_share(s.start), fmt_share(s.end), s.z_start,
            s.runs_before, s.runs_after))
    if len(shifts) > SHOW_ROWS:
        print("  " + t("changes.shown", n=SHOW_ROWS, total=len(shifts)))
    print()


def print_changes(runs: list[Run], changes: list[Change], path: str) -> None:
    print()
    if not changes:
        print(t("changes.empty", path=path))
        print(t("changes.format"))
        return
    print(t("changes.title", n=len(changes), file=os.path.basename(path)))
    print("  " + t("changes.explain", n=POINT_RUNS, days=LOOKBACK.days))
    print("  " + t("changes.sigma"))
    print()
    for index, change in enumerate(changes):
        print_boundary(change, boundary_shifts(runs, changes, index))
    print("  " + t("changes.caveat_growth"))
    print("  " + t("changes.caveat_same_day"))
    print()
