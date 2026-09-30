"""Настройки пользователя: где данные, кто игрок, какой язык.

Лежат в папке пользователя, а не рядом с программой: `%APPDATA%\\aim-telemetry`
на Windows, `~/.config/aim-telemetry` в остальных системах. Там же журнал
изменений (changes.txt) и список бенчмарков (benchmarks.txt). При первом
запуске всё заполняется автопоиском по файлам Steam.
"""

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from datetime import datetime

from . import aimbeast, kovaaks, kovaaks_api, steam
from .i18n import LANGS, t

APP_NAME = "aim-telemetry"
CONFIG_NAME = "config.json"
CHANGES_NAME = "changes.txt"
BENCHMARKS_NAME = "benchmarks.txt"
DASHBOARD_NAME = "dashboard.html"

DEFAULT_BENCHMARKS = (
    (2834, "Voltaic S5.5 Intermediate"),
    (2835, "Voltaic S5.5 Novice"),
    (2070, "Voltaic S5.5 Advanced"),
    (2336, "Viscose S2 Medium"),
    (2335, "Viscose S2 Easier"),
    (2844, "Avasive S2 Medium"),
    (2843, "Avasive S2 Easier"),
)


@dataclass
class Config:
    lang: str = "ru"
    steam_id: str = ""
    kovaaks_user: str = ""      # ник на kovaaks.com — для каталога бенчмарков
    kovaaks_dir: str = ""       # папка stats KovaaK's
    aimbeast_dir: str = ""      # папка Trainer Aimbeast
    steam_log: str = ""         # gameprocess_log.txt — время запусков Aimbeast
    test_date: str = ""         # контрольный замер, ГГГГ-ММ-ДД — отсчёт в дашборде
    dashboard: str = ""         # куда сохранять дашборд; пусто — в папку настроек


# ── пути ─────────────────────────────────────────────────────────────────────

def config_dir() -> str:
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return os.path.join(os.environ["APPDATA"], APP_NAME)
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, APP_NAME)


def cache_dir() -> str:
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        return os.path.join(os.environ["LOCALAPPDATA"], APP_NAME, "cache")
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, APP_NAME)


def config_path(folder: str | None = None) -> str:
    return os.path.join(folder or config_dir(), CONFIG_NAME)


def changes_path(folder: str | None = None) -> str:
    return os.path.join(folder or config_dir(), CHANGES_NAME)


def benchmarks_path(folder: str | None = None) -> str:
    return os.path.join(folder or config_dir(), BENCHMARKS_NAME)


def dashboard_path(cfg: Config, folder: str | None = None) -> str:
    return cfg.dashboard or os.path.join(folder or config_dir(), DASHBOARD_NAME)


# ── чтение и запись ──────────────────────────────────────────────────────────

def load(path: str) -> Config | None:
    """Настройки из файла. Незнакомые ключи игнорируются, битый файл — как отсутствующий."""
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    known = {f.name for f in fields(Config)}
    return Config(**{k: str(v) for k, v in raw.items() if k in known and v is not None})


def save(cfg: Config, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(asdict(cfg), fh, ensure_ascii=False, indent=2)


def set_value(cfg: Config, key: str, value: str) -> Config:
    """Новая копия настроек с изменённым полем; неверное значение — SystemExit с пояснением."""
    known = {f.name for f in fields(Config)}
    if key not in known:
        raise SystemExit(t("config.unknown_key", key=key, keys=", ".join(sorted(known))))
    if key == "lang" and value not in LANGS:
        raise SystemExit(t("config.bad_lang", langs=", ".join(LANGS)))
    if key == "test_date" and value:
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise SystemExit(t("config.bad_date")) from None
    return Config(**{**asdict(cfg), key: value})


# ── автопоиск ────────────────────────────────────────────────────────────────

def discover(cfg: Config, check_online: bool = True) -> Config:
    """Заполняет пустые поля по файлам Steam. Заполненные не трогает — их выбрал человек."""
    values = asdict(cfg)
    root = steam.steam_root()
    if root:
        kovaaks_game = steam.app_dir(root, kovaaks.APP_ID)
        aimbeast_game = steam.app_dir(root, aimbeast.APP_ID)
        found = {
            "kovaaks_dir": kovaaks_game and os.path.join(kovaaks_game, *kovaaks.STATS_SUBDIR),
            "aimbeast_dir": aimbeast_game and os.path.join(aimbeast_game, *aimbeast.TRAINER_SUBDIR),
            "steam_log": steam.process_log(root),
        }
        user = steam.last_user(root)
        if user:
            found["steam_id"] = user.steam_id
            # ник KovaaK's обычно совпадает с именем в Steam — проверяем по API
            if check_online and user.persona and kovaaks_api.steam_id_of(user.persona) == user.steam_id:
                found["kovaaks_user"] = user.persona
        for key, value in found.items():
            if not values[key] and value and (key in ("steam_id", "kovaaks_user") or os.path.exists(value)):
                values[key] = value
    return Config(**values)


def write_default_files(folder: str) -> None:
    """Журнал изменений и список бенчмарков с пояснениями — только если их ещё нет."""
    changes = changes_path(folder)
    if not os.path.exists(changes):
        with open(changes, "w", encoding="utf-8") as fh:
            fh.write(t("files.changes_header") + "\n")
    benches = benchmarks_path(folder)
    if not os.path.exists(benches):
        with open(benches, "w", encoding="utf-8") as fh:
            fh.write(t("files.benchmarks_header") + "\n")
            fh.writelines("%-5d  # %s\n" % item for item in DEFAULT_BENCHMARKS)


def ensure(folder: str | None = None, check_online: bool = True) -> tuple[Config, bool]:
    """Настройки из папки; при первом запуске — создать автопоиском. Второе значение — «создано»."""
    folder = folder or config_dir()
    path = config_path(folder)
    cfg = load(path)
    created = cfg is None
    if created:
        cfg = discover(Config(), check_online)
        os.makedirs(folder, exist_ok=True)
        save(cfg, path)
    write_default_files(folder)
    return cfg, created
