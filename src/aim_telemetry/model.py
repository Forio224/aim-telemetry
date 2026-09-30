"""Общая модель прогона и статистические помощники."""

import statistics
from datetime import datetime
from typing import NamedTuple

# относительный допуск, в котором сенса считается той же (46.65 и 46.650002)
SENS_TOLERANCE = 0.01

# нижняя граница разброса. У сценариев вроде Ground Plaza собственный разброс
# около 1%, и любое отклонение на них раздувается в «катастрофу»
SPREAD_FLOOR = 0.02


class Run(NamedTuple):
    """Один прогон сценария — из KovaaK's или Aimbeast."""

    when: datetime
    scenario: str
    score: float
    accuracy: float
    kills: int
    overshots: int | None   # Aimbeast перелёты не пишет
    kind: str
    sens: str
    dpi: str
    fov: str
    res: str


def mean(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def cv(values: list[float]) -> float:
    """Коэффициент вариации: разброс, очищенный от масштаба сценария."""
    if len(values) < 2:
        return 0.0
    average = statistics.mean(values)
    return statistics.pstdev(values) / average if average else 0.0


def spread(values: list[float]) -> float:
    """Разброс для сравнения с нормой — не ниже SPREAD_FLOOR."""
    return max(cv(values), SPREAD_FLOOR)


def same_sens(a: str, b: str) -> bool:
    """Одна ли это сенса с точностью до SENS_TOLERANCE. Нечисловые — строгое равенство."""
    try:
        x, y = float(a), float(b)
    except ValueError:
        return a == b
    return abs(x - y) <= SENS_TOLERANCE * max(abs(y), 1e-9)
