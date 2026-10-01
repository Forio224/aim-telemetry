"""Расчёты отчёта без вывода: окно, сессии, перерыв, строки таблицы, план.

Общая часть для консоли (cli) и дашборда (dashboard). Метки и действия — коды,
тексты к ним — в messages.
"""

from datetime import datetime, timedelta
from typing import NamedTuple

from . import aimbeast
from .diagnose import (
    BELOW,
    CEILING,
    EVEN,
    MIN_HISTORY,
    NOT_ACTIONABLE,
    PLATEAU,
    UNSTABLE,
    Baseline,
    Progress,
    diagnose,
    progress,
)
from .i18n import t
from .model import Run, cv, mean, median, same_sens

# разрыв между прогонами, после которого считаем, что началась новая сессия
SESSION_GAP = timedelta(minutes=40)
# перерыв, после которого сессия в среднем ниже нормы (~0.4σ на истории автора)
LONG_BREAK = timedelta(days=3)

# порядок в «взять в работу»; действие к метке — todo.<код> в messages
TODO_PRIORITY = {BELOW: 0, UNSTABLE: 1, PLATEAU: 2, CEILING: 2, EVEN: 3}


class TodoItem(NamedTuple):
    scenario: str
    label: str      # код метки; действие — todo.<label>


def aimbeast_to_runs(raw: list[aimbeast.AimbeastRun]) -> list[Run]:
    """Прогоны Aimbeast в общем виде. Сенсы по прогонам нет — ставим «?»."""
    return [Run(when=r.when, scenario=r.scenario, score=r.score, accuracy=r.accuracy,
                kills=r.kills, overshots=None, kind="click" if r.kills else "track",
                sens="?", dpi="?", fov="?", res="?")
            for r in raw]


def load_aimbeast(trainer_dir: str, log_path: str | None = None) -> list[Run]:
    return aimbeast_to_runs(aimbeast.load_runs(trainer_dir, log_path))


# ── окно и сессии ────────────────────────────────────────────────────────────

def split_sessions(runs: list[Run]) -> list[list[Run]]:
    """Разрезает историю на сессии по паузе длиннее SESSION_GAP."""
    sessions = []
    current = []
    for run in runs:
        if current and run.when - current[-1].when > SESSION_GAP:
            sessions.append(current)
            current = []
        current.append(run)
    if current:
        sessions.append(current)
    return sessions


def break_before(runs: list[Run], window: list[Run]) -> int | None:
    """Целых суток перерыва перед окном — от последнего прогона до него.

    None, если перерыв короче LONG_BREAK или до окна ничего не играли. Считать
    по окну до фильтра по сценарию: иначе «перерыв» найдётся внутри сессии.
    """
    start = window[0].when
    previous = next((r for r in reversed(runs) if r.when < start), None)
    if previous is None or start - previous.when < LONG_BREAK:
        return None
    return (start - previous.when).days


def pick_window(runs: list[Run], days: int | None, session: int) -> tuple[list[Run], str]:
    if days:
        cutoff = runs[-1].when - timedelta(days=days)
        return [r for r in runs if r.when >= cutoff], t("window.days", n=days)

    sessions = split_sessions(runs)
    index = min(session, len(sessions))
    title = t("window.last") if index == 1 else t("window.nth", n=index)
    return sessions[-index], title


# ── строки таблицы и план ────────────────────────────────────────────────────

def scenario_progress(runs: list[Run], window: list[Run], scenario: str) -> Progress:
    """Долгая картина на сенсе окна, по всей истории до конца окна."""
    sens = [r.sens for r in window if r.scenario == scenario][-1]
    end = window[-1].when
    own = [r for r in runs
           if r.scenario == scenario and r.when <= end and same_sens(r.sens, sens)]
    return progress(own, end)


def scenario_row(scenario: str, window: list[Run], base: Baseline, prog: Progress,
                 cutoff: datetime | None, break_days: int | None = None) -> dict:
    runs = [r for r in window if r.scenario == scenario]
    scores = [r.score for r in runs]
    verdict = diagnose(scores, base)
    kills = sum(r.kills for r in runs)
    known = all(r.overshots is not None for r in runs)
    # подсказки — пары (код, параметры); текст соберёт вывод на своём языке
    hints = [[verdict.hint, verdict.params or {}]] if verdict.hint else []
    if prog.plateau:
        hints.append([PLATEAU, {"days": prog.days_since_best}])
    # перерыв не меняет диагноз — только объясняет просадку
    if verdict.label == BELOW and break_days is not None:
        hints.append(["after_break", {"days": break_days}])
    return {
        "scenario": scenario, "n": len(runs), "avg": mean(scores), "best": base.best,
        "norm": median(base.scores) if len(base.scores) >= MIN_HISTORY else None,
        "crosses": cutoff is not None and not base.since_change,
        "deficit": (mean(scores) - base.best) / base.best * 100 if base.best else 0.0,
        "cv": cv(scores) * 100, "acc": mean([r.accuracy for r in runs]),
        "over": sum(r.overshots for r in runs) / kills if kills and known else None,
        "trend": prog.trend, "since_best": prog.days_since_best, "plateau": prog.plateau,
        "label": verdict.label, "hints": hints,
    }


def scenario_table(window: list[Run], runs: list[Run], baselines: dict[str, Baseline],
                   cutoff: datetime | None, break_days: int | None = None) -> list[dict]:
    """Строки по всем сценариям окна: сначала с базой, по отставанию от максимума."""
    table = [scenario_row(s, window, baselines[s], scenario_progress(runs, window, s), cutoff,
                          break_days)
             for s in sorted({r.scenario for r in window})]
    return sorted(table, key=lambda r: (r["norm"] is None, r["deficit"]))


def todo(table: list[dict], top: int) -> list[TodoItem]:
    """Что взять в работу: сначала просадки, потом нестабильность, плато и потолок."""
    candidates = []
    for row in table:
        if row["label"] in NOT_ACTIONABLE:
            continue
        # плато важнее «ровно»: рекорд стоит, хотя сессия прошла нормально
        label = PLATEAU if row["plateau"] and row["label"] == EVEN else row["label"]
        candidates.append((TODO_PRIORITY[label], row["deficit"], label, row["scenario"]))
    return [TodoItem(scenario, label)
            for _, _, label, scenario in sorted(candidates, key=lambda c: c[:2])[:top]]


def hint_text(hints: list) -> str:
    """Подсказки строки таблицы одной строкой на текущем языке."""
    return "; ".join(t("hint." + code, **params) for code, params in hints)
