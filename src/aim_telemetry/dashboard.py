"""Дашборд: один локальный HTML с зашитыми данными, без сервера.

Собирает всё, что считает консольный отчёт, в JSON и вместе со стилями,
скриптом и библиотекой графиков из папки web/ складывает в один файл. Данные
не покидают компьютер, страница работает без сети; из сети грузятся только
шрифты (без них — системные) и бенчмарки с kovaaks.com при сборке.
"""

import json
import os
import re
import webbrowser
from datetime import datetime, timedelta
from importlib import resources

from . import __version__, i18n, kovaaks_api
from . import bench as aim_bench
from . import changes as aim_changes
from .diagnose import build_baselines, progress
from .entry import entry_cost
from .model import Run, same_sens
from .report import (
    break_before,
    scenario_status,
    scenario_table,
    split_sessions,
    todo,
)

# куски страницы в web/ и места, куда они встают в template.html
PARTS = {"/*__CSS__*/": "dashboard.css", "/*__ECHARTS__*/": "echarts.min.js",
         "/*__JS__*/": "dashboard.js"}
PLACEHOLDER = "/*__AIM_DATA__*/null"

RECENT_DAYS = 30       # вкладка по умолчанию — тренажёр, где больше попыток за этот срок
TODO_TOP = 5
NEAREST_TOP = 6
RUN_MINUTES = 1.0      # длительность последнего прогона сессии, которой нет в разнице времени


def ts(moment: datetime) -> int:
    """Время для JS: миллисекунды, местное время как есть."""
    return int(moment.timestamp() * 1000)


def clean(value):
    """float → округлённый, чтобы JSON не раздувался хвостами 0.30000000000000004."""
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


# ── история ──────────────────────────────────────────────────────────────────

def scenarios_payload(runs: list[Run], now: datetime,
                      tagged: dict[str, str] | None = None) -> tuple[list[dict], list[str]]:
    """Все прогоны по сценариям колонками + долгая картина на текущей сенсе."""
    sens_list = sorted({r.sens for r in runs})
    sens_index = {s: i for i, s in enumerate(sens_list)}
    grouped = {}
    for run in runs:
        grouped.setdefault(run.scenario, []).append(run)

    out = []
    for name, own in grouped.items():
        current = own[-1].sens
        same = [r for r in own if same_sens(r.sens, current)]
        prog = progress(same, now)
        status = scenario_status([r.score for r in same])
        out.append({
            "name": name, "kind": own[-1].kind, "n": len(own), "last": ts(own[-1].when),
            "tag": (tagged or {}).get(name),
            "sens": current, "best": max(r.score for r in same),
            "trend": prog.trend, "sinceBest": prog.days_since_best, "plateau": prog.plateau,
            "status": status["status"], "last3": status["recent"], "share": status["share"],
            "t": [ts(r.when) for r in own], "s": [r.score for r in own],
            "a": [r.accuracy for r in own], "k": [sens_index[r.sens] for r in own],
        })
    out.sort(key=lambda s: -s["last"])
    return out, sens_list


def days_payload(runs: list[Run]) -> list[dict]:
    """Объём по дням: прогоны и примерные минуты (длина сессий)."""
    days = {}
    for session in split_sessions(runs):
        minutes = (session[-1].when - session[0].when).total_seconds() / 60 + RUN_MINUTES
        for run in session:
            day = days.setdefault(run.when.date().isoformat(), {"runs": 0, "minutes": 0.0})
            day["runs"] += 1
        days[session[0].when.date().isoformat()]["minutes"] += minutes
    return [{"d": d, **v} for d, v in sorted(days.items())]


# ── сессия и вход в сценарий ─────────────────────────────────────────────────

def session_payload(runs: list[Run], changes: list[aim_changes.Change]) -> dict:
    window = split_sessions(runs)[-1]
    change = aim_changes.last_change(changes, window[0].when)
    cutoff = change.when if change else None
    baselines, _ = build_baselines(runs, window, cutoff)
    break_days = break_before(runs, window)
    table = scenario_table(window, runs, baselines, cutoff, break_days)
    return {
        "start": ts(window[0].when), "end": ts(window[-1].when), "n": len(window),
        "breakDays": break_days, "rows": table,
        "todo": [item._asdict() for item in todo(table, TODO_TOP)],
        "setup": {"sens": window[-1].sens, "dpi": window[-1].dpi, "fov": window[-1].fov,
                  "res": window[-1].res},
    }


def entry_payload(runs: list[Run], changes: list[aim_changes.Change]) -> dict | None:
    """Цена входа в сценарий по всей истории — не по последней сессии."""
    cost = entry_cost(runs, changes)
    return cost._asdict() if cost else None


def changes_payload(runs: list[Run], changes: list[aim_changes.Change]) -> list[dict]:
    return [{"t": ts(c.when), "text": c.text,
             "shifts": [s._asdict() for s in aim_changes.boundary_shifts(runs, changes, i)]}
            for i, c in enumerate(changes)]


# ── бенчмарк ─────────────────────────────────────────────────────────────────

def bench_payload(bench_id: int, name: str, data: dict, runs: list[Run], now: datetime) -> dict:
    info, rows, states = aim_bench.analyze(bench_id, name, data, runs, now)
    overall = None
    if info.levels:
        best = aim_bench.harmonic([s.energy for s in states])
        form = aim_bench.harmonic([s.form_energy if s.form_energy is not None else s.energy
                                   for s in states])
        overall = {"best": best, "form": form,
                   "missing": [s.name.strip() for s in states if s.form_energy is None]}
    return {
        "id": bench_id, "name": name, "progress": data.get("benchmark_progress", 0),
        "siteRank": int(data.get("overall_rank") or 0), "sens": runs[-1].sens,
        "ranks": [{"name": n, "color": c} for n, c in zip(info.ranks, info.colors)],
        "levels": info.levels, "overall": overall,
        "categories": [{**s._asdict(), "name": s.name.strip(), "scenarios": [
            {**r._asdict(), "short": aim_bench.short_name(r.scenario),
             "last_played": ts(r.last_played) if r.last_played else None}
            for r in rows if r.category == s.name]} for s in states],
        "notes": [list(n) for n in aim_bench.before_test_notes(states, info.ranks)],
        "nearest": [n._asdict() for n in aim_bench.nearest(rows, states, NEAREST_TOP, info.ranks)],
    }


def catalog_payload(username: str | None) -> list[dict] | None:
    """Все бенчмарки kovaaks.com с рангом игрока. None — ника нет или сайт недоступен.

    Ответ — чужие данные: берём только записи нужной формы.
    """
    if not username:
        return None
    try:
        items = kovaaks_api.fetch_catalog(username)
    except kovaaks_api.ApiError:
        return None
    out = []
    for item in items:
        bench_id, name = item.get("benchmarkId"), item.get("benchmarkName")
        if item.get("type") != "benchmark" or not isinstance(bench_id, int) or not isinstance(name, str):
            continue
        rank = item.get("rankName")
        color = item.get("rankColor")
        out.append({"id": bench_id, "name": name.strip(), "author": str(item.get("benchmarkAuthor") or ""),
                    "rank": rank if isinstance(rank, str) and rank != "No Rank" else None,
                    "color": color if isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color) else None})
    return out


def benches_payload(runs: list[Run], bench_list: list[tuple[int, str]], steam_id: str,
                    now: datetime) -> list[dict]:
    """Все бенчмарки из списка. Недоступный — с ошибкой, чтобы дашборд сказал об этом."""
    fetched = kovaaks_api.fetch_benches([bench_id for bench_id, _ in bench_list], steam_id)
    out = []
    for bench_id, name in bench_list:
        data = fetched[bench_id]
        out.append({"id": bench_id, "name": name, "error": str(data)}
                   if isinstance(data, Exception) else bench_payload(bench_id, name, data, runs, now))
    return out


# ── сборка ───────────────────────────────────────────────────────────────────

def source_payload(label: str, runs: list[Run], changes: list[aim_changes.Change],
                   now: datetime, extra: dict | None = None,
                   tagged: dict[str, str] | None = None) -> dict:
    scenarios, sens_list = scenarios_payload(runs, now, tagged)
    return {
        "label": label, "scenarios": scenarios, "sensList": sens_list,
        "recent": sum(r.when >= now - timedelta(days=RECENT_DAYS) for r in runs),
        "days": days_payload(runs), "session": session_payload(runs, changes),
        "entry": entry_payload(runs, changes),
        "changes": changes_payload(runs, changes), **(extra or {}),
    }


def web_file(name: str) -> str:
    return resources.files(__package__).joinpath("web", name).read_text(encoding="utf-8")


def script_safe(text: str) -> str:
    """«</script» внутри вставки закрыл бы тег раньше времени. Остальное не трогаем:
    в минифицированном коде «</» может быть частью выражения."""
    return re.sub(r"</(script)", lambda m: "<\\/" + m.group(1), text, flags=re.IGNORECASE)


def page(data: dict) -> str:
    """Шаблон с подставленными стилями, скриптами и данными."""
    html = web_file("template.html")
    for marker in (*PARTS, PLACEHOLDER):
        if marker not in html:
            raise SystemExit(i18n.t("dash.template_broken", marker=marker))
    for marker, name in PARTS.items():
        part = web_file(name)
        html = html.replace(marker, part if name.endswith(".css") else script_safe(part))
    # в JSON «</» бывает только внутри строк — там его можно экранировать целиком
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return html.replace(PLACEHOLDER, payload)


def write_dashboard(sources: dict[str, dict], changes: list[aim_changes.Change],
                    test_date: str | None, out_path: str, bench_file: str | None = None) -> str:
    data = clean({
        "generated": ts(datetime.now()), "testDate": test_date, "version": __version__,
        "benchFile": bench_file,
        "changes": [{"t": ts(c.when), "text": c.text} for c in changes],
        "sources": sources, "i18n": i18n.catalog(),
    })
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(page(data))
    return out_path


def open_in_browser(path: str) -> None:
    webbrowser.open("file:///" + os.path.abspath(path).replace("\\", "/"))
