"""Бенчмарки KovaaK's: рекорды с сайта против текущей формы.

Рекорд показывает, что ты когда-то смог. Форма — медиана последних прогонов на
текущей сенсе — ближе к тому, что покажет контрольный замер.

Для любого бенчмарка считается «уровень»: номер ранга плюс доля пути до
следующего порога (2.4 — сорок процентов от второго ранга к третьему). Ранги,
«что добрать» и «ближе всего к рангу» считаются по уровню. У Voltaic поверх
этого есть vt-energy — уровень, пересчитанный в шкалу 100/200/…/1200.
"""

import math
import re
import statistics
from datetime import datetime
from typing import NamedTuple

from .diagnose import TREND_DAYS, trend_per_week
from .i18n import t
from .kovaaks_api import ApiError, fetch_bench
from .model import Run, same_sens

RANK_NAMES = ["Platinum", "Diamond", "Jade", "Master"]
RANK_ENERGY = [500, 600, 700, 800]   # energy на порогах Voltaic Intermediate
# первый ранг уровня Voltaic → energy на его пороге (Novice / Intermediate / Advanced)
VOLTAIC_BASE = {"Iron": 100, "Platinum": 500, "Grandmaster": 900}
ENERGY_STEP = 100
RECENT_RUNS = 5                      # сколько последних прогонов брать в «форму»
STALE_DAYS = 10                      # категория без игры дольше — форма по ней устарела
TIER_SUFFIX = re.compile(r" (Novice|Intermediate|Advanced) S\d+$")


class BenchInfo(NamedTuple):
    """Что за бенчмарк: ранги из ответа сайта и шкала energy, если это Voltaic."""

    id: int
    name: str
    ranks: list[str]                 # без «No Rank»
    colors: list[str]
    levels: list[float] | None       # energy на порогах; None — бенчмарк не Voltaic


class BenchRow(NamedTuple):
    """Один сценарий бенчмарка: рекорд, пороги и форма."""

    category: str
    scenario: str
    best: float
    maxes: list[float]
    energy: float | None
    form: float | None          # медиана последних RECENT_RUNS на текущей сенсе
    form_energy: float | None
    trend: float | None         # доля в неделю, как в aim_diagnose
    last_played: datetime | None   # на любой сенсе
    level: float = 0.0
    form_level: float | None = None


class CategoryState(NamedTuple):
    name: str
    energy: float | None        # по рекордам: максимум по сценариям
    form_energy: float | None   # по форме; None — на текущей сенсе не играно
    days_idle: int | None       # дней без игры; None — не играно никогда
    level: float = 0.0
    form_level: float | None = None
    site_rank: int = 0          # ранг категории, как его считает сайт


class Nearest(NamedTuple):
    """Сценарий, чей следующий порог поднимет свою категорию."""

    category: str
    scenario: str
    need: float
    rank: str
    share: float


# ── шкалы ────────────────────────────────────────────────────────────────────

def energy_levels(ranks: list[str]) -> list[float] | None:
    """Шкала energy по названиям рангов, если это уровень Voltaic."""
    base = VOLTAIC_BASE.get(ranks[0]) if ranks else None
    return [base + ENERGY_STEP * i for i in range(len(ranks))] if base else None


def bench_info(bench_id: int, name: str, data: dict) -> BenchInfo:
    ranks = [r for r in data.get("ranks", []) if isinstance(r, dict)][1:]   # [0] — No Rank
    names = [str(r.get("name", "?")).strip() for r in ranks]
    colors = [str(r.get("color", "")).strip() for r in ranks]
    return BenchInfo(bench_id, name, names, colors, energy_levels(names))


def energy(score: float, maxes: list[float], levels: list[float] = RANK_ENERGY) -> float:
    """vt-energy: линейно между порогами рангов, выше последнего — с тем же шагом."""
    if score <= 0:
        return 0.0
    if score >= maxes[-1]:
        return levels[-1] + (score - maxes[-1]) / (maxes[-1] - maxes[-2]) * (levels[-1] - levels[-2])
    for i in range(len(maxes) - 1, 0, -1):
        if score >= maxes[i - 1]:
            return levels[i - 1] + (score - maxes[i - 1]) / (maxes[i] - maxes[i - 1]) * (levels[i] - levels[i - 1])
    return score / maxes[0] * levels[0]   # ниже первого порога — приблизительно


def level(score: float, maxes: list[float]) -> float:
    """Номер ранга с долей пути до следующего: 0 — без ранга, len(maxes) — последний."""
    if score <= 0 or not maxes:
        return 0.0
    if score < maxes[0]:
        return score / maxes[0]
    if score >= maxes[-1]:
        step = maxes[-1] - maxes[-2] if len(maxes) > 1 else maxes[-1]
        return len(maxes) + (score - maxes[-1]) / step
    i = sum(score >= m for m in maxes)
    return i + (score - maxes[i - 1]) / (maxes[i] - maxes[i - 1])


def rank_name(value: float, names: list[str] = RANK_NAMES,
              levels: list[float] = RANK_ENERGY) -> str:
    """Ранг по energy."""
    passed = [name for name, need in zip(names, levels) if value >= need]
    return passed[-1] if passed else "—"


def level_name(value: float | None, names: list[str]) -> str:
    """Ранг по уровню."""
    if value is None or value < 1 or not names:
        return "—"
    return names[min(int(math.floor(value)), len(names)) - 1]


def harmonic(values: list[float]) -> float:
    return len(values) / sum(1 / max(v, 1e-9) for v in values) if values else 0.0


def short_name(scenario: str) -> str:
    return TIER_SUFFIX.sub("", scenario)


# ── строки и категории ───────────────────────────────────────────────────────

def bench_rows(data: dict, runs: list[Run], sens: str, now: datetime,
               levels: list[float] | None = RANK_ENERGY) -> list[BenchRow]:
    rows = []
    for category, block in data["categories"].items():
        for scenario, info in block["scenarios"].items():
            best = info["score"] / 100   # сайт отдаёт очки ×100
            maxes = [float(x) for x in info["rank_maxes"]]
            played = [r for r in runs if r.scenario == scenario]
            own = [r for r in played if same_sens(r.sens, sens)]
            form = statistics.median(r.score for r in own[-RECENT_RUNS:]) if own else None
            rows.append(BenchRow(
                category, scenario, best, maxes,
                energy(best, maxes, levels) if levels else None, form,
                energy(form, maxes, levels) if levels and form is not None else None,
                trend_per_week(own, now) if own else None,
                played[-1].when if played else None,
                level(best, maxes), level(form, maxes) if form is not None else None))
    return rows


def category_states(rows: list[BenchRow], now: datetime,
                    site_ranks: dict[str, int] | None = None) -> list[CategoryState]:
    states = []
    for name in dict.fromkeys(r.category for r in rows):
        group = [r for r in rows if r.category == name]
        forms = [r.form_energy for r in group if r.form_energy is not None]
        form_levels = [r.form_level for r in group if r.form_level is not None]
        last = max((r.last_played for r in group if r.last_played), default=None)
        energies = [r.energy for r in group if r.energy is not None]
        states.append(CategoryState(
            name, max(energies) if energies else None, max(forms) if forms else None,
            (now - last).days if last else None,
            max(r.level for r in group), max(form_levels) if form_levels else None,
            (site_ranks or {}).get(name, 0)))
    return states


def before_test_notes(states: list[CategoryState],
                      names: list[str] = RANK_NAMES) -> list[tuple[str, str, dict]]:
    """Что добрать до замера: (категория, код, параметры); текст — note.<код> в messages."""
    notes = []
    for s in sorted(states, key=lambda s: s.form_level if s.form_level is not None else -1):
        label = s.name.strip()
        if s.days_idle is None:
            notes.append((label, "never", {}))
        elif s.form_level is None:
            notes.append((label, "other_sens", {}))
        elif level_name(s.form_level, names) != level_name(s.level, names):
            notes.append((label, "form_below", {"form": level_name(s.form_level, names),
                                                "best": level_name(s.level, names)}))
        elif s.days_idle >= STALE_DAYS:
            notes.append((label, "stale", {"days": s.days_idle}))
    return notes


def nearest(rows: list[BenchRow], states: list[CategoryState], top: int,
            names: list[str] = RANK_NAMES) -> list[Nearest]:
    """Сценарии, чей следующий порог реально поднимет уровень своей категории."""
    category_level = {s.name: s.level for s in states}
    options = []
    for row in rows:
        idx = next((i for i, m in enumerate(row.maxes) if m > row.best), None)
        if idx is None or idx + 1 <= category_level[row.category]:
            continue
        need = row.maxes[idx] - row.best
        options.append(Nearest(row.category.strip(), row.scenario, need,
                               names[idx] if idx < len(names) else "#%d" % (idx + 1),
                               need / row.maxes[idx]))
    return sorted(options, key=lambda o: o.share)[:top]


def analyze(bench_id: int, name: str, data: dict, runs: list[Run],
            now: datetime) -> tuple[BenchInfo, list[BenchRow], list[CategoryState]]:
    info = bench_info(bench_id, name, data)
    rows = bench_rows(data, runs, runs[-1].sens, now, info.levels)
    site_ranks = {k: int(v.get("category_rank") or 0) for k, v in data["categories"].items()}
    return info, rows, category_states(rows, now, site_ranks)


# ── вывод ────────────────────────────────────────────────────────────────────

def fmt_opt(value: float | None, fmt: str, width: int) -> str:
    return fmt % value if value is not None else "—".rjust(width)


def value_cells(info: BenchInfo, energy_value: float | None, level_value: float | None) -> str:
    """energy у Voltaic, уровень у остальных."""
    if info.levels:
        return fmt_opt(energy_value and int(energy_value), "%6d", 6)
    return fmt_opt(level_value, "%6.2f", 6)


def print_bench_table(info: BenchInfo, rows: list[BenchRow], states: list[CategoryState]) -> None:
    unit = t("bench.energy") if info.levels else t("bench.level")
    header = "%-12s %-22s %8s %6s %-10s %11s %8s %6s %7s %7s" % (
        t("col.category"), t("col.scenario"), t("col.best"), unit[:6], t("col.rank"),
        t("col.to_next"), t("col.form"), t("col.by_form"), t("col.trend"), t("col.last"))
    print(header)
    print("-" * len(header))
    for state in states:
        group = [r for r in rows if r.category == state.name]
        for i, row in enumerate(group):
            nxt = next((m for m in row.maxes if m > row.best), None)
            gap = "%.0f → %.0f" % (nxt - row.best, nxt) if nxt else t("bench.max_plus")
            last = row.last_played.strftime("%d.%m") if row.last_played else "—"
            print("%-12s %-22s %8.1f %s %-10s %11s %8s %6s %7s %7s" % (
                state.name.strip()[:12] if i == 0 else "", short_name(row.scenario)[:22], row.best,
                value_cells(info, row.energy, row.level), level_name(row.level, info.ranks)[:10],
                gap, fmt_opt(row.form, "%8.1f", 8), value_cells(info, row.form_energy, row.form_level),
                fmt_opt(row.trend and row.trend * 100, "%+5.1f%%", 7), last))
        form = (t("bench.cat_form", rank=level_name(state.form_level, info.ranks))
                if state.form_level is not None else t("bench.cat_no_form"))
        idle = ("" if state.days_idle is None or state.days_idle < STALE_DAYS
                else " · !! " + t("bench.cat_idle", days=state.days_idle))
        print("%-12s = %s · %s%s" % ("", t("bench.cat_best", rank=level_name(state.level, info.ranks)),
                                     form, idle))
    print()


def print_overall(info: BenchInfo, states: list[CategoryState], data: dict) -> None:
    if not info.levels:
        rank = int(data.get("overall_rank") or 0)
        print(t("bench.site_rank", rank=info.ranks[rank - 1] if 0 < rank <= len(info.ranks) else "—"))
        print()
        return
    by_best = harmonic([s.energy for s in states])
    by_form = harmonic([s.form_energy if s.form_energy is not None else s.energy for s in states])
    missing = [s.name.strip() for s in states if s.form_energy is None]
    print(t("bench.overall"))
    print("  " + t("bench.by_best", value=int(by_best), rank=rank_name(by_best, info.ranks, info.levels)))
    line = "  " + t("bench.by_form", value=int(by_form), rank=rank_name(by_form, info.ranks, info.levels))
    print(line + ("   " + t("bench.missing", names=", ".join(missing)) if missing else ""))
    print()


def note_text(code: str, params: dict) -> str:
    return t("note." + code, **params)


def print_before_test(states: list[CategoryState], names: list[str]) -> None:
    print(t("bench.before_test"))
    notes = before_test_notes(states, names)
    for name, code, params in notes:
        print("  %-12s %s" % (name, note_text(code, params)))
    if not notes:
        print("  " + t("bench.all_in_form"))
    print()


def print_nearest(rows: list[BenchRow], states: list[CategoryState], top: int,
                  names: list[str]) -> None:
    print(t("bench.nearest"))
    options = nearest(rows, states, top, names)
    if not options:
        print("  " + t("bench.nearest_none"))
    for o in options:
        print("  %-12s %-34s %s" % (o.category[:12], o.scenario[:34],
                                    t("bench.nearest_row", need="%.0f" % o.need, rank=o.rank,
                                      share="%.1f" % (o.share * 100))))
    print()


def print_bench(runs: list[Run], bench_id: int, name: str, steam_id: str, top: int,
                now: datetime | None = None) -> None:
    try:
        data = fetch_bench(bench_id, steam_id)
    except ApiError as exc:
        raise SystemExit(t("bench.fetch_failed", error=exc)) from None
    now = now or datetime.now()
    info, rows, states = analyze(bench_id, name, data, runs, now)
    print()
    print(t("bench.title", name=name, id=bench_id, progress="%.0f" % data.get("benchmark_progress", 0)))
    print("  " + t("bench.explain_form", n=RECENT_RUNS, sens=runs[-1].sens))
    print("  " + t("bench.explain_cols", unit=t("bench.energy") if info.levels else t("bench.level"),
                   days=TREND_DAYS))
    print()
    print_bench_table(info, rows, states)
    print_overall(info, states, data)
    print_before_test(states, info.ranks)
    print_nearest(rows, states, top, info.ranks)
