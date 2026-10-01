"""Цена входа в сценарий: насколько первый прогон блока ниже остальных.

Блок — прогоны одного сценария подряд внутри сессии; вернулся к сценарию
после другого — новый блок. Каждый прогон сравнивается с нормой своего
сценария до его сессии (как в диагнозе) и переводится в её разбросы.

Цена — среднее первых прогонов минус среднее остальных, а не сам уровень
первых: против прошлой нормы на растущем навыке выше неё все прогоны, и
вход выглядел бы бесплатным. Одиночные блоки входят наравне с длинными —
после хорошего первого прогона сценарий бросают чаще, и без них цена
завышена. Интервал — бутстреп целыми сессиями: входы одной тренировки
делят сон, день и форму, независимыми их считать нельзя.
"""

import random
from typing import NamedTuple

from . import changes as aim_changes
from .diagnose import MIN_HISTORY, build_baselines
from .model import Run, mean, median, same_sens, spread
from .report import SESSION_GAP, split_sessions

MIN_SESSIONS = 5           # меньше сессий с уровнями — цену не показываем
BOOTSTRAP_SAMPLES = 2000
BOOTSTRAP_SEED = 224       # один и тот же интервал на одних и тех же данных
INTERVAL = 0.95


class EntryCost(NamedTuple):
    cost: float            # первые минус остальные, в разбросах сценария
    low: float
    high: float
    blocks: int            # первых прогонов с нормой
    sessions: int
    scenarios: int


def scenario_blocks(runs: list[Run]) -> list[list[Run]]:
    """Режет историю на блоки: смена сценария или пауза длиннее сессии."""
    blocks = []
    for run in runs:
        prev = blocks[-1][-1] if blocks else None
        if prev and prev.scenario == run.scenario and run.when - prev.when <= SESSION_GAP:
            blocks[-1].append(run)
        else:
            blocks.append([run])
    return blocks


def levels(runs: list[Run], changes: list[aim_changes.Change]) -> list[float | None]:
    """Уровень каждого прогона против нормы сценария; None — нормы нет.

    Норма та же, что в диагнозе: прогоны до начала его сессии на той же сенсе.
    Все прогоны сессии меряются одной нормой — иначе у второго прогона в норме
    уже сидит первый, и рост навыка за день попадает в цену входа.
    """
    out = []
    for session in split_sessions(runs):
        change = aim_changes.last_change(changes, session[0].when)
        baselines, _ = build_baselines(runs, session, change.when if change else None)
        session_sens = {r.scenario: r.sens for r in session}
        for run in session:
            scores = baselines[run.scenario].scores
            center = median(scores)
            if (len(scores) < MIN_HISTORY or not center
                    or not same_sens(run.sens, session_sens[run.scenario])):
                out.append(None)
                continue
            out.append((run.score - center) / center / spread(scores))
    return out


class SessionLevels(NamedTuple):
    entries: list[float]   # уровни первых прогонов блоков
    others: list[float]    # уровни остальных
    scenarios: set[str]    # сценарии, у которых есть уровень входа


def session_levels(runs: list[Run], changes: list[aim_changes.Change]) -> list[SessionLevels]:
    """По каждой сессии: уровни первых прогонов блоков и остальных."""
    level_of = dict(zip(map(id, runs), levels(runs, changes)))
    out = []
    for session in split_sessions(runs):
        found = SessionLevels([], [], set())
        for block in scenario_blocks(session):
            for i, run in enumerate(block):
                level = level_of[id(run)]
                if level is None:
                    continue
                if i:
                    found.others.append(level)
                else:
                    found.entries.append(level)
                    found.scenarios.add(run.scenario)
        out.append(found)
    return out


def gap(sample: list[SessionLevels]) -> float | None:
    entries = [z for s in sample for z in s.entries]
    others = [z for s in sample for z in s.others]
    return mean(entries) - mean(others) if entries and others else None


def entry_cost(runs: list[Run], changes: list[aim_changes.Change]) -> EntryCost | None:
    """Цена входа по всей истории или None, если сессий с уровнями мало."""
    per_session = [s for s in session_levels(runs, changes) if s.entries or s.others]
    cost = gap(per_session)
    if len(per_session) < MIN_SESSIONS or cost is None:
        return None

    rng = random.Random(BOOTSTRAP_SEED)
    samples = sorted(g for g in (gap(rng.choices(per_session, k=len(per_session)))
                                 for _ in range(BOOTSTRAP_SAMPLES)) if g is not None)
    tail = (1 - INTERVAL) / 2
    return EntryCost(cost, samples[int(tail * len(samples))],
                     samples[int((1 - tail) * len(samples)) - 1],
                     blocks=sum(len(s.entries) for s in per_session), sessions=len(per_session),
                     scenarios=len(set().union(*(s.scenarios for s in per_session))))
