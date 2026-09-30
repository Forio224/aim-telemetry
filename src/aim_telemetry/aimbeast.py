"""Чтение локальной истории Aimbeast для aim-stats.py.

Aimbeast хранит прогоны не файлом на прогон, как KovaaK's, а массивами на сценарий:
`Trainer/Statistics/<Normal|Ranked|Custom>/<сценарий>.json` в UTF-16. У каждого
прогона там только дата без времени и нет сенсы. Время восстанавливается так:

  * `Training Data/training_data_<год>.json` — по дням, какие сценарии сыграны,
    сколько прогонов и секунд. Ключи идут в порядке игры (сверено с mtime файлов);
  * `gameprocess_log.txt` Steam — точное время каждого запуска игры.

  * mtime файла сценария — точный конец его последнего блока. Для последнего
    дня сценария это опорная точка, между опорами время растягивается.

Начало дня берётся из первого запуска, прогоны раскладываются подряд по
длительностям сценариев и подтягиваются к опорам. Без опор минуты внутри
дня — чистое игровое время без меню, то есть занижены.

Конфиг (`Config.cfg`) — сжатый zlib-архив UE4 с сериализованным объектом Config_C.
В нём только текущие настройки, истории по ним нет.
"""

import glob
import json
import os
import re
import struct
import zlib
from datetime import date, datetime, time, timedelta
from typing import NamedTuple

APP_ID = "1100990"
TRAINER_SUBDIR = ("Aimbeast", "Trainer")    # внутри папки игры

# запуски короче этого — перезапуск или вылет, начало дня по ним не ставим
MIN_LAUNCH = timedelta(minutes=3)
# если лога Steam нет или он уже ротирован — день начинается в полдень
FALLBACK_START = time(12, 0)
# шаг для прогонов, которых нет в журнале дня
FALLBACK_STEP = timedelta(seconds=60)
# во сколько раз реальное время может превышать игровое между опорами (меню,
# перерывы). Больше — значит опора от другого запуска, отрезок не растягиваем
MAX_STRETCH = 2.0

UE_TAG = 0x9E2A83C1
UE_HEADER = 0x20      # tag, пусто, размер блока, суммарные размеры
UE_CHUNK_ENTRY = 16   # на каждый блок: сжатый и исходный размер по int64

LOG_LINE_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] .*AppID %s\b" % APP_ID)
LAUNCH_RE = re.compile(r'adding PID \d+ as a tracked process ".*\\Aimbeast\.exe"$')

# поля конфига, которые имеют смысл для сравнения прогонов
CONFIG_FLOATS = ("SensivityXMainValue", "DPI", "FOV")
CONFIG_STRINGS = ("SensitivityScale", "FOVType", "resolution")


class AimbeastRun(NamedTuple):
    """Прогон Aimbeast с восстановленным временем."""

    when: datetime
    scenario: str
    score: float
    accuracy: float
    kills: int
    anchored: bool   # время дня привязано к логу Steam или mtime, а не к заглушке


class DayBlock(NamedTuple):
    """Сценарий в журнале дня: сколько прогонов и секунд на него ушло."""

    scenario: str
    runs: int
    seconds: int


class Launch(NamedTuple):
    start: datetime
    end: datetime


# сценарий → дата → прогоны (очки, точность, убийства)
Stats = dict[str, dict[date, list[tuple[float, float, int]]]]


# ── файлы статистики ─────────────────────────────────────────────────────────

def read_utf16_json(path: str) -> dict:
    with open(path, encoding="utf-16") as fh:
        return json.load(fh)


def parse_day(text: str) -> date | None:
    """`23/9/2026` — формат дат Aimbeast."""
    try:
        return datetime.strptime(text, "%d/%m/%Y").date()
    except ValueError:
        return None


def parse_rows(data: dict) -> dict[date, list[tuple[float, float, int]]]:
    """Параллельные массивы файла сценария → прогоны по датам. Кривая строка пропускается."""
    by_day = {}
    rows = zip(data.get("Date", []), data.get("Score", []),
               data.get("Accuracy", []), data.get("Kills", []))
    for day_text, score, accuracy, kills in rows:
        day = parse_day(str(day_text))
        try:
            run = (float(score), float(accuracy), int(kills))
        except (TypeError, ValueError):
            continue
        if day is not None:
            by_day.setdefault(day, []).append(run)
    return by_day


def load_stats(trainer_dir: str) -> tuple[Stats, dict[str, datetime], int]:
    """Сценарий → дата → прогоны в порядке игры, mtime файлов и число нераспознанных файлов."""
    stats, mtimes, skipped = {}, {}, 0
    for path in glob.glob(os.path.join(trainer_dir, "Statistics", "*", "*.json")):
        try:
            data = read_utf16_json(path)
            modified = datetime.fromtimestamp(os.path.getmtime(path))
        except (OSError, UnicodeError, json.JSONDecodeError):
            skipped += 1
            continue
        by_day = parse_rows(data) if isinstance(data, dict) else {}
        if not by_day:
            skipped += 1
            continue
        name = os.path.basename(path)[:-5]
        stats[name] = by_day
        mtimes[name] = modified
    return stats, mtimes, skipped


def load_day_order(trainer_dir: str) -> dict[date, list[DayBlock]]:
    """Журнал тренировок: по дням, в порядке игры."""
    out = {}
    pattern = os.path.join(trainer_dir, "Training Data", "training_data_*.json")
    for path in sorted(glob.glob(pattern)):
        try:
            data = read_utf16_json(path)
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        for key, blocks in data.items():
            day = parse_day(key)
            if day is None or not isinstance(blocks, dict):
                continue   # «Streak Overrides» и прочее служебное
            out[day] = [block for name, info in blocks.items()
                        if (block := day_block(name, info)) is not None]
    return out


def day_block(name: str, info: object) -> DayBlock | None:
    """Запись журнала дня. Незнакомая форма — None: порядок дня без неё не сломается."""
    if not isinstance(info, dict):
        return None
    try:
        return DayBlock(name, int(info.get("Completed Sessions") or 0),
                        int(info.get("Total Time") or 0))
    except (TypeError, ValueError):
        return None


# ── лог Steam ────────────────────────────────────────────────────────────────

def parse_launches(lines: list[str]) -> list[Launch]:
    """Запуски игры: старт — строка с Aimbeast.exe, конец — последняя строка AppID до следующего."""
    launches = []
    start = last = None
    for line in lines:
        m = LOG_LINE_RE.match(line)
        if not m:
            continue
        stamp = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        if LAUNCH_RE.search(line.rstrip()):
            if start is not None:
                launches.append(Launch(start, last))
            start = stamp
        last = stamp
    if start is not None:
        launches.append(Launch(start, last))
    return launches


def load_launches(log_path: str) -> list[Launch]:
    try:
        with open(log_path, encoding="utf-8", errors="ignore") as fh:
            return parse_launches(fh.read().splitlines())
    except OSError:
        return []


def day_start(day: date, launches: list[Launch]) -> datetime | None:
    """Начало игры в этот день: первый полноценный запуск, пересекающий сутки."""
    midnight = datetime.combine(day, time())
    next_midnight = midnight + timedelta(days=1)
    for launch in launches:
        if launch.end - launch.start < MIN_LAUNCH:
            continue
        if launch.start < next_midnight and launch.end > midnight:
            return max(launch.start, midnight)
    return None


# ── сборка прогонов ──────────────────────────────────────────────────────────

def day_blocks(day: date, stats: Stats, blocks: list[DayBlock]) -> list[DayBlock]:
    """Блоки дня в порядке игры. Сценарии, которых нет в журнале, — в конец."""
    known = {block.scenario for block in blocks}
    order = [b for b in blocks if day in stats.get(b.scenario, {})]
    extra = sorted(name for name, by_day in stats.items() if day in by_day and name not in known)
    return order + [DayBlock(name, 0, 0) for name in extra]


def run_offsets(blocks: list[DayBlock], stats: Stats, day: date) -> list[list[float]]:
    """Игровые секунды от начала дня до конца каждого прогона, по блокам."""
    out, cursor = [], 0.0
    for block in blocks:
        count = len(stats[block.scenario][day])
        step = (block.seconds / count if block.seconds
                else FALLBACK_STEP.total_seconds())
        out.append([cursor + step * (i + 1) for i in range(count)])
        cursor += step * count
    return out


def time_points(start: datetime | None,
                anchors: list[tuple[float, datetime]]) -> list[tuple[float, datetime]]:
    """Опорные точки «игровые секунды → реальное время», монотонные по обеим осям."""
    points = [(0.0, start)] if start else []
    for offset, real in sorted(anchors, key=lambda a: a[0]):
        if not points:
            points.append((0.0, real - timedelta(seconds=offset)))
        last_offset, last_real = points[-1]
        # реального времени не может пройти меньше игрового — значит, опора чужая
        if offset > last_offset and (real - last_real).total_seconds() >= offset - last_offset:
            points.append((offset, real))
    return points


def warp(points: list[tuple[float, datetime]], offset: float) -> datetime:
    """Игровые секунды → реальное время по опорам.

    Отрезок между опорами растягивается равномерно, пока растяжка правдоподобна.
    Иначе между ними был перерыв: прогоны ставятся вплотную к следующей опоре.
    """
    for (off0, real0), (off1, real1) in zip(points, points[1:]):
        if offset > off1:
            continue
        span, gap = off1 - off0, (real1 - real0).total_seconds()
        if gap <= MAX_STRETCH * span:
            return real0 + timedelta(seconds=(offset - off0) * gap / span)
        return real1 - timedelta(seconds=off1 - offset)
    last_offset, last_real = points[-1]
    return last_real + timedelta(seconds=offset - last_offset)


def lay_out_day(day: date, stats: Stats, mtimes: dict[str, datetime],
                blocks: list[DayBlock], start: datetime | None) -> list[AimbeastRun]:
    """Раскладывает прогоны дня по времени: блоки подряд, привязка к запуску и mtime."""
    order = day_blocks(day, stats, blocks)
    offsets = run_offsets(order, stats, day)
    # mtime — конец блока, только если этот день у сценария последний
    anchors = [(ends[-1], mtimes[b.scenario]) for b, ends in zip(order, offsets)
               if b.scenario in mtimes and mtimes[b.scenario].date() == day
               and max(stats[b.scenario]) == day]
    points = time_points(start, anchors)
    anchored = bool(points)
    if not points:
        points = [(0.0, datetime.combine(day, FALLBACK_START))]

    runs = []
    for block, ends in zip(order, offsets):
        for (score, accuracy, kills), end in zip(stats[block.scenario][day], ends):
            runs.append(AimbeastRun(warp(points, end), block.scenario, score, accuracy,
                                    kills, anchored))
    return runs


def scan(trainer_dir: str, log_path: str | None = None) -> tuple[list[AimbeastRun], int]:
    """Прогоны и число файлов статистики, которые не удалось разобрать."""
    stats, mtimes, skipped = load_stats(trainer_dir)
    order = load_day_order(trainer_dir)
    launches = load_launches(log_path) if log_path else []
    days = sorted({day for by_day in stats.values() for day in by_day})
    runs = []
    for day in days:
        runs += lay_out_day(day, stats, mtimes, order.get(day, []), day_start(day, launches))
    return sorted(runs, key=lambda r: r.when), skipped


def load_runs(trainer_dir: str, log_path: str | None = None) -> list[AimbeastRun]:
    return scan(trainer_dir, log_path)[0]


def ranked_scenarios(trainer_dir: str) -> set[str]:
    """Сценарии ранкед-плейлиста: у них своя папка статистики."""
    pattern = os.path.join(trainer_dir, "Statistics", "Ranked", "*.json")
    return {os.path.basename(path)[:-5] for path in glob.glob(pattern)}


# ── конфиг ───────────────────────────────────────────────────────────────────

def unpack_ue(raw: bytes) -> bytes:
    """Сжатый архив UE4: заголовок, таблица блоков, затем zlib-блоки подряд."""
    tag, _, chunk, _, total = struct.unpack_from("<IIqqq", raw, 0)
    if tag != UE_TAG or chunk <= 0:
        raise ValueError("не архив UE4")
    count = (total + chunk - 1) // chunk
    pos = UE_HEADER + UE_CHUNK_ENTRY * count
    out = []
    for i in range(count):
        packed, _ = struct.unpack_from("<qq", raw, UE_HEADER + UE_CHUNK_ENTRY * i)
        out.append(zlib.decompress(raw[pos:pos + packed]))
        pos += packed
    return b"".join(out)


def property_value(blob: bytes, name: str) -> bytes | None:
    """Сырое значение свойства: за именем идёт int64 смещения, потом само значение."""
    key = struct.pack("<i", len(name) + 1) + name.encode() + b"\x00"
    at = blob.find(key)
    return blob[at + len(key) + 8:] if at >= 0 else None


def read_config(trainer_dir: str) -> dict[str, str]:
    """Текущие сенса, DPI, FOV и разрешение из Config.cfg. Пустой словарь, если не читается."""
    try:
        with open(os.path.join(trainer_dir, "Config.cfg"), "rb") as fh:
            blob = unpack_ue(fh.read())
    except (OSError, ValueError, struct.error, zlib.error):
        return {}

    out = {}
    for name in CONFIG_FLOATS:
        value = property_value(blob, name)
        if value is not None and len(value) >= 4:
            out[name] = "%g" % round(struct.unpack_from("<f", value)[0], 4)
    for name in CONFIG_STRINGS:
        value = property_value(blob, name)
        if value is not None and len(value) >= 4:
            size = struct.unpack_from("<i", value)[0]
            if 0 < size <= len(value) - 4:
                out[name] = value[4:4 + size].rstrip(b"\x00").decode("utf-8", "replace")
    return out
