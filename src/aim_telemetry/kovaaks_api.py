"""Запросы к kovaaks.com и список бенчмарков для дашборда.

API не документирован как публичный: запросов делаем немного, ответы кэшируем
на CACHE_TTL, чтобы частые пересборки дашборда не нагружали сайт. Всё, что
отсюда приходит, — чужие данные: код проверяет форму ответа, а не доверяет ей.
"""

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import __version__
from .i18n import t

API = "https://kovaaks.com/webapp-backend"
BENCH_URL = API + "/benchmarks/player-progress-rank-benchmark?benchmarkId=%d&steamId=%s&page=0&max=100"
CATALOG_URL = API + "/benchmarks/player-progress-rank?username=%s&page=%d&max=%d"
PROFILE_URL = API + "/user/profile/by-username?username=%s"
TIMEOUT = 15
CACHE_TTL = 3600           # секунд: бенчмарк за час не меняется настолько, чтобы спрашивать снова
CATALOG_PAGE = 100
CATALOG_MAX_PAGES = 20     # предохранитель: сейчас в каталоге ~7 страниц
PARALLEL = 4               # одновременных запросов при сборке дашборда

LINE_RE = re.compile(r"^\s*(\d+)\s*(?:#\s*(.*))?$")


class ApiError(Exception):
    """kovaaks.com недоступен или ответил не тем."""


_cache_dir: str | None = None


def set_cache_dir(path: str | None) -> None:
    """Куда складывать ответы. None — без кэша (тесты, --no-cache)."""
    global _cache_dir
    _cache_dir = path


def cache_path(url: str) -> str | None:
    if not _cache_dir:
        return None
    return os.path.join(_cache_dir, hashlib.sha1(url.encode()).hexdigest() + ".json")


def read_cache(url: str) -> object | None:
    path = cache_path(url)
    if not path or not os.path.exists(path) or time.time() - os.path.getmtime(path) > CACHE_TTL:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def write_cache(url: str, data: object) -> None:
    path = cache_path(url)
    if not path:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    except OSError:
        pass   # без кэша работает так же, только медленнее


def get_json(url: str) -> object:
    cached = read_cache(url)
    if cached is not None:
        return cached
    agent = "aim-telemetry/%s (local training analyzer)" % __version__
    request = urllib.request.Request(url, headers={"User-Agent": agent})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ApiError("kovaaks.com: %s" % exc) from exc
    write_cache(url, data)
    return data


def steam_id_of(username: str) -> str | None:
    """Steam ID аккаунта KovaaK's по нику — чтобы проверить, что ник угадан верно."""
    try:
        data = get_json(PROFILE_URL % urllib.parse.quote(username))
    except ApiError:
        return None
    return str(data.get("steamId")) if isinstance(data, dict) and data.get("steamId") else None


def fetch_bench(bench_id: int, steam_id: str) -> dict:
    data = get_json(BENCH_URL % (bench_id, steam_id))
    if not isinstance(data, dict) or not data.get("categories"):
        raise ApiError(t("api.bench_empty", id=bench_id))
    return data


def fetch_benches(ids: list[int], steam_id: str) -> dict[int, dict | ApiError]:
    """Несколько бенчмарков параллельно. Ошибка одного не роняет остальные."""
    def one(bench_id: int) -> dict | ApiError:
        try:
            return fetch_bench(bench_id, steam_id)
        except ApiError as exc:
            return exc
    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        return dict(zip(ids, pool.map(one, ids)))


def fetch_catalog(username: str) -> list[dict]:
    """Все бенчмарки KovaaK's с рангом игрока в каждом."""
    items = []
    for page in range(CATALOG_MAX_PAGES):
        data = get_json(CATALOG_URL % (urllib.parse.quote(username), page, CATALOG_PAGE))
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise ApiError(t("api.catalog_bad"))
        items += data["data"]
        if not data["data"] or len(items) >= int(data.get("total", 0)):
            break
    return items


def parse_bench_list(lines: list[str]) -> list[tuple[int, str]]:
    """Строки `2834  # Voltaic S5.5 Intermediate` → (id, название). Порядок сохраняется."""
    out, seen = [], set()
    for line in lines:
        m = LINE_RE.match(line)
        if m and int(m.group(1)) not in seen:
            seen.add(int(m.group(1)))
            out.append((int(m.group(1)), (m.group(2) or "").strip() or t("bench.default_name", id=m.group(1))))
    return out


def load_bench_list(path: str) -> list[tuple[int, str]]:
    try:
        with open(path, encoding="utf-8") as fh:
            return parse_bench_list(fh.read().splitlines())
    except OSError:
        return []
