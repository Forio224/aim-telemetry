"""Норма, диагноз и долгие тренды по сценарию.

Норма — медиана последних прогонов до окна, а не среднее всей истории: на
растущем сценарии старые слабые прогоны иначе тянут её вниз. Если после
последнего изменения из журнала (changes) уже набралась база, норма
берётся только оттуда — сравнивать с прогонами на другом железе нельзя.

Сдвиг от нормы считается значимым, только если он больше шума: разброс
базы и число прогонов с обеих сторон дают границу примерно в 95%.

Диагноз — код и параметры, а не текст: текст собирает i18n на нужном языке.
"""

import math
import statistics
from datetime import datetime, timedelta
from typing import NamedTuple

from .model import Run, cv, mean, median, same_sens, spread

BASELINE_RUNS = 12     # норма — медиана стольких последних прогонов до окна
MIN_HISTORY = 4        # меньше — нормы нет
MIN_WINDOW_RUNS = 3    # по одному-двум прогонам разброс и потолок не судятся

GROWTH = 0.03          # +3% к норме — рост
DROP = -0.05           # -5% — просадка
CONFIDENCE_Z = 2.0     # граница шума: ~95% при нормальном разбросе
UNSTABLE_CV = 0.05     # разброс выше 5% — нестабильность
UNSTABLE_RATIO = 1.5   # ...либо в полтора раза выше собственной нормы
CEILING_CV = 0.03      # разброс ниже 3% при результате у максимума — потолок
CEILING_NEAR = 0.97

TREND_DAYS = 14        # тренд — по прогонам за последние две недели
TREND_MIN_RUNS = 6
TREND_MIN_DAYS = 3     # и минимум за три разных дня, иначе это тренд одной сессии
PLATEAU_DAYS = 10      # столько дней без рекорда...
PLATEAU_MIN_DAYS = 3   # ...при стольких днях игры за последние TREND_DAYS...
PLATEAU_TREND = 0.01   # ...и тренде слабее +1%/нед — плато. Растёт — это возврат формы

# коды диагнозов; тексты — label.<код> и hint.<код> в messages
NO_BASE, ABOVE, BELOW, NOISE, FEW = "no_base", "above", "below", "noise", "few"
UNSTABLE, CEILING, PLATEAU, EVEN = "unstable", "ceiling", "plateau", "even"
# метки, по которым действовать рано
NOT_ACTIONABLE = (NO_BASE, ABOVE, NOISE, FEW)


class Verdict(NamedTuple):
    """Диагноз по сценарию: код метки, код подсказки и её параметры."""

    label: str
    hint: str | None = None
    params: dict | None = None


class Baseline(NamedTuple):
    """С чем сравнивать окно по одному сценарию."""

    scores: list[float]    # последние BASELINE_RUNS прогонов до окна
    best: float | None     # личный максимум до окна на той же сенсе
    since_change: bool     # вся база после последнего изменения из журнала


class Progress(NamedTuple):
    """Долгая картина по сценарию: тренд и давность рекорда."""

    trend: float | None    # доля нормы в неделю, +0.02 = +2%/нед
    days_since_best: int
    plateau: bool


# ── база ─────────────────────────────────────────────────────────────────────

def build_baselines(runs: list[Run], window: list[Run],
                    cutoff: datetime | None) -> tuple[dict[str, Baseline], dict[str, int]]:
    """Нормы по сценариям окна и число прогонов, отброшенных из-за другой сенсы.

    В базу идут только прогоны раньше окна и на той же сенсе, что в окне.
    """
    start = window[0].when
    window_sens = {r.scenario: r.sens for r in window}   # окно отсортировано: последняя
    history, excluded = {}, {}
    for run in runs:
        sens = window_sens.get(run.scenario)
        if sens is None or run.when >= start:
            continue
        if not same_sens(run.sens, sens):
            excluded[run.scenario] = excluded.get(run.scenario, 0) + 1
            continue
        history.setdefault(run.scenario, []).append(run)

    baselines = {}
    for scenario in window_sens:
        past = history.get(scenario, [])
        recent = [r for r in past if cutoff and r.when >= cutoff]
        since_change = cutoff is not None and len(recent) >= MIN_HISTORY
        pool = recent if since_change else past
        baselines[scenario] = Baseline(
            scores=[r.score for r in pool[-BASELINE_RUNS:]],
            best=max((r.score for r in past), default=None),
            since_change=since_change)
    return baselines, excluded


# ── диагноз ──────────────────────────────────────────────────────────────────

def noise_limit(base_spread: float, now_runs: int, base_runs: int) -> float:
    """Сдвиг, который ещё объясняется разбросом, в долях нормы."""
    return CONFIDENCE_Z * base_spread * math.sqrt(1 / now_runs + 1 / base_runs)


def runs_needed(shift: float, base_spread: float, base_runs: int) -> int | None:
    """Сколько прогонов в окне нужно, чтобы такой сдвиг вышел за шум (строго)."""
    k = (shift / (CONFIDENCE_Z * base_spread)) ** 2 - 1 / base_runs
    if k <= 0:
        return None
    need = max(math.floor(1 / k), 1)
    # формула даёт границу; на ней плавающая точка может дать ровно равенство
    while noise_limit(base_spread, need, base_runs) >= shift:
        need += 1
    return need


def shift_verdict(rel: float, now_runs: int, hist: list[float]) -> Verdict | None:
    """Выше/ниже нормы — или «в шуме», если сдвиг не выходит за разброс."""
    if DROP < rel < GROWTH:
        return None
    base_spread = spread(hist)
    if abs(rel) > noise_limit(base_spread, now_runs, len(hist)):
        code = ABOVE if rel > 0 else BELOW
        return Verdict(code, code, {"pct": "%.0f" % abs(rel * 100)})
    need = runs_needed(abs(rel), base_spread, len(hist))
    shift = "%+.0f" % (rel * 100)
    if need:
        return Verdict(NOISE, "noise_more", {"shift": shift, "n": max(need - now_runs, 1)})
    return Verdict(NOISE, "noise_never", {"shift": shift})


def diagnose(now: list[float], base: Baseline) -> Verdict:
    hist = base.scores
    if len(hist) < MIN_HISTORY:
        return Verdict(NO_BASE, NO_BASE, {"n": MIN_HISTORY - len(hist)})

    rel = (mean(now) - median(hist)) / median(hist)
    shifted = shift_verdict(rel, len(now), hist)
    if shifted:
        return shifted
    if len(now) < MIN_WINDOW_RUNS:
        return Verdict(FEW, FEW, {"n": len(now)})

    cv_now, cv_hist = cv(now), cv(hist)
    if cv_now > max(UNSTABLE_CV, UNSTABLE_RATIO * cv_hist):
        return Verdict(UNSTABLE, UNSTABLE,
                       {"now": "%.1f" % (cv_now * 100), "norm": "%.1f" % (cv_hist * 100)})
    best = base.best or max(now)
    if cv_now < CEILING_CV and mean(now) >= CEILING_NEAR * best:
        return Verdict(CEILING, CEILING, {})
    return Verdict(EVEN)


# ── долгая картина ───────────────────────────────────────────────────────────

def trend_per_week(runs: list[Run], end: datetime) -> float | None:
    """Наклон результата за TREND_DAYS в долях среднего за неделю."""
    recent = [r for r in runs if r.when >= end - timedelta(days=TREND_DAYS)]
    if len(recent) < TREND_MIN_RUNS or len({r.when.date() for r in recent}) < TREND_MIN_DAYS:
        return None
    days = [(r.when - recent[0].when).total_seconds() / 86400 for r in recent]
    scores = [r.score for r in recent]
    slope = statistics.linear_regression(days, scores).slope
    return slope * 7 / mean(scores) if mean(scores) else None


def progress(runs: list[Run], end: datetime) -> Progress:
    """Тренд и давность рекорда по прогонам одного сценария на одной сенсе."""
    best = max(runs, key=lambda r: (r.score, -r.when.timestamp()))   # первый выход на максимум
    days = (end.date() - best.when.date()).days
    trend = trend_per_week(runs, end)
    recent_days = {r.when.date() for r in runs if r.when >= end - timedelta(days=TREND_DAYS)}
    plateau = (days >= PLATEAU_DAYS and len(recent_days) >= PLATEAU_MIN_DAYS
               and (trend is None or trend < PLATEAU_TREND))
    return Progress(trend, days, plateau)
