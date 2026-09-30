"""Командная строка: отчёт по сессии, бенчмарк, журнал изменений, дашборд, настройки.

    aim-telemetry                     последняя сессия KovaaK's
    aim-telemetry --days 14           всё за 14 дней
    aim-telemetry --source aimbeast   то же по Aimbeast
    aim-telemetry --bench             бенчмарк: рекорды и форма
    aim-telemetry --changes           что дало каждое изменение из журнала
    aim-telemetry --dashboard         HTML-дашборд, откроется в браузере
    aim-telemetry --setup / --set / --config   настройки

Собранный .exe, запущенный двойным кликом, сразу строит дашборд.
"""

import argparse
import os
import sys
import traceback
from datetime import datetime

from . import __version__, aimbeast, bench, config, dashboard, kovaaks, kovaaks_api
from . import changes as journal
from .diagnose import MIN_HISTORY, NO_BASE, Baseline, build_baselines
from .i18n import LANGS, set_lang, t
from .model import Run
from .report import (
    ShapePoint,
    aggregate_shape,
    aimbeast_to_runs,
    find_fatigue,
    find_warmup,
    hint_text,
    pick_window,
    scenario_table,
    session_shape,
    split_sessions,
    todo,
)

DEFAULT_BENCH = (2834, "Voltaic S5.5 Intermediate")


# ── вывод: среда ─────────────────────────────────────────────────────────────

def print_environment(window: list[Run], excluded: dict[str, int]) -> None:
    print(t("env.title"))
    setups = {(r.sens, r.dpi, r.fov, r.res) for r in window}
    last = window[-1]
    print("  " + t("env.setup", sens=last.sens, dpi=last.dpi, fov=last.fov, res=last.res))
    print("  " + (t("env.changed", n=len(setups)) if len(setups) > 1 else t("env.same")))
    if excluded:
        print("  " + t("env.excluded"))
        for scenario, count in sorted(excluded.items(), key=lambda kv: -kv[1])[:6]:
            print("     %-38s %s" % (scenario[:38], t("common.runs", n=count)))
        if len(excluded) > 6:
            print("     " + t("env.excluded_more", n=len(excluded) - 6))


def print_aimbeast_environment(trainer_dir: str) -> None:
    """У Aimbeast настройки есть только текущие — по прогонам их не восстановить."""
    settings = aimbeast.read_config(trainer_dir)
    print(t("env.title"))
    if settings:
        print("  " + t("env.aimbeast_config", sens=settings.get("SensivityXMainValue", "?"),
                       scale=settings.get("SensitivityScale", ""), dpi=settings.get("DPI", "?"),
                       fov=settings.get("FOV", "?"), fov_type=settings.get("FOVType", "?"),
                       res=settings.get("resolution", "?")))
    else:
        print("  " + t("env.aimbeast_no_config"))
    print("  !! " + t("env.aimbeast_no_sens"))
    print("  " + t("env.aimbeast_time"))


def print_change_note(change: journal.Change | None, baselines: dict[str, Baseline],
                      end: datetime) -> None:
    if change is None:
        print("  " + t("env.no_changes"))
        print()
        return
    based = [b for b in baselines.values() if len(b.scores) >= MIN_HISTORY]
    fresh = sum(b.since_change for b in based)
    print("  " + t("env.last_change", date=change.when.strftime("%d.%m"),
                   days=(end - change.when).days, text=change.text))
    if fresh == len(based):
        print("  " + t("env.norm_all_after", n=fresh))
    else:
        print("  " + t("env.norm_some_after", n=fresh, total=len(based)))
    print()


# ── вывод: сценарии ──────────────────────────────────────────────────────────

def label_text(row: dict) -> str:
    text = t("label." + row["label"])
    return text + (" · " + t("label.plateau") if row["plateau"] else "")


def format_row(row: dict) -> str:
    def opt(value, fmt: str, width: int) -> str:
        return fmt % value if value is not None else "—".rjust(width)

    norm = opt(row["norm"], "%8.1f", 8) + ("*" if row["norm"] is not None and row["crosses"]
                                           else " ")
    return "%-28s %4d %8.1f %s %8s %7s %6.1f%% %5.1f%% %7s %7s %4d  %s" % (
        row["scenario"][:28], row["n"], row["avg"], norm, opt(row["best"], "%8.1f", 8),
        opt(row["deficit"] if row["best"] else None, "%+6.1f%%", 7), row["cv"], row["acc"],
        opt(row["over"], "%7.2f", 7), opt(row["trend"] and row["trend"] * 100, "%+5.1f%%", 7),
        row["since_best"], label_text(row))


def print_scenarios(window: list[Run], runs: list[Run], baselines: dict[str, Baseline],
                    cutoff: datetime | None) -> list[dict]:
    header = "%-28s %4s %8s %9s %8s %7s %7s %6s %7s %7s %4s  %s" % (
        t("col.scenario"), t("col.runs"), t("col.avg"), t("col.norm"), t("col.max"),
        t("col.deficit"), t("col.spread"), t("col.acc"), t("col.over"), t("col.trend"),
        t("col.since_best"), t("col.verdict"))
    print(t("scen.title"))
    print(header)
    print("-" * len(header))

    table = scenario_table(window, runs, baselines, cutoff)
    for row in table:
        print(format_row(row))

    fresh = [r for r in table if r["norm"] is None]
    if fresh:
        print()
        print("  " + t("scen.no_base", n=len(fresh)))
    print()

    # «нет базы» уже сосчитаны строкой выше — по одной на сценарий только шумят
    comments = [r for r in table if r["hints"] and r["label"] != NO_BASE]
    if comments:
        print(t("scen.meaning"))
        for row in sorted(comments, key=lambda r: r["deficit"]):
            print("  %-32s %s" % (row["scenario"][:32], hint_text(row["hints"])))
        print()
    return table


# ── вывод: форма, план, легенда ──────────────────────────────────────────────

def print_shape_rows(points: list[ShapePoint], with_sessions: bool) -> None:
    if len(points) > 24:
        print("  " + t("shape.first_24", n=len(points)))
    rows = [("  %-7s" % t("shape.run"), "%6d", lambda p: p.index),
            ("  %-7s" % t("shape.level"), "%+6.1f", lambda p: p.level)]
    if with_sessions:
        rows.append(("  %-7s" % t("shape.sessions"), "%6d", lambda p: p.sessions))
    for title, fmt, pick in rows:
        print(title + "".join(fmt % pick(point) for point in points[:24]))


def print_shape_verdict(points: list[ShapePoint]) -> None:
    levels = [point.level for point in points]
    warmup = find_warmup(levels)
    fatigue = find_fatigue(levels, warmup)
    if warmup:
        print("  " + t("shape.warmup", n=warmup + 1, minutes=round(points[warmup].minutes)))
    else:
        print("  " + t("shape.no_warmup"))
    if fatigue:
        print("  " + t("shape.fatigue", n=fatigue + 1, minutes=round(points[fatigue].minutes)))
    else:
        print("  " + t("shape.no_fatigue"))


def print_shape(window: list[Run], baselines: dict[str, Baseline], aggregate: bool) -> None:
    """Форма сессии: одна сессия целиком или среднее по всем сессиям окна."""
    if aggregate:
        sessions = split_sessions(window)
        points = aggregate_shape(sessions, baselines)
        if not points:
            if len(sessions) == 1:
                print_shape(window, baselines, aggregate=False)
            return
        print(t("shape.title_avg", n=max(point.sessions for point in points)))
        print_shape_rows(points, with_sessions=True)
        print_shape_verdict(points)
        print("  " + t("shape.sessions_note"))
        print()
        return

    if len(window) < 6:
        return
    points = session_shape(window, baselines)
    print(t("shape.title"))
    print_shape_rows(points, with_sessions=False)
    print_shape_verdict(points)
    print("  " + t("shape.single_note"))
    print()


def print_todo(table: list[dict], top: int) -> None:
    print(t("todo.title", n=top))
    print("-" * 60)
    items = todo(table, top)
    if not items:
        print("  " + t("todo.none"))
    for i, item in enumerate(items, 1):
        print("%d. %-32s %-16s %s" % (i, item.scenario[:32], t("label." + item.label),
                                      t("todo." + item.label)))
    print()


def print_legend() -> None:
    print(t("legend.title"))
    for key in ("norm", "max", "spread", "acc", "over", "trend", "since_best"):
        print("  " + t("legend." + key))
    print()
    for key in ("shift", "noise", "level", "unstable", "ceiling", "plateau"):
        print("  " + t("legend." + key))
    print()


# ── источники ────────────────────────────────────────────────────────────────

def warn_skipped(skipped: int, total: int, folder: str) -> None:
    """Файлы с правильным именем, которые не разобрались: смена формата у игры."""
    if skipped and not total:
        raise SystemExit(t("load.format_unknown", folder=folder, n=skipped))
    if skipped:
        print("!! " + t("load.skipped", n=skipped), file=sys.stderr)


def source_dir(cfg: config.Config, source: str, override: str | None) -> str:
    folder = override or (cfg.aimbeast_dir if source == "aimbeast" else cfg.kovaaks_dir)
    if not folder:
        raise SystemExit(t("load.not_configured", source=source))
    if not os.path.isdir(folder):
        raise SystemExit(t("load.no_folder", folder=folder))
    return folder


def load_kovaaks(folder: str) -> list[Run]:
    runs, skipped = kovaaks.scan(folder)
    warn_skipped(skipped, len(runs), folder)
    return runs


def load_aimbeast_checked(folder: str, log: str) -> list[Run]:
    raw, skipped = aimbeast.scan(folder, log or None)
    warn_skipped(skipped, len(raw), folder)
    return aimbeast_to_runs(raw)


def load_source(cfg: config.Config, args: argparse.Namespace) -> list[Run]:
    if args.source == "aimbeast" and args.bench:
        raise SystemExit(t("load.no_bench_aimbeast"))
    folder = source_dir(cfg, args.source, args.dir)
    args.dir = folder
    runs = (load_aimbeast_checked(folder, cfg.steam_log) if args.source == "aimbeast"
            else load_kovaaks(folder))
    if not runs:
        raise SystemExit(t("load.no_runs", folder=folder))
    return runs


def filter_scenario(runs: list[Run], needle: str | None) -> list[Run]:
    return [r for r in runs if needle.lower() in r.scenario.lower()] if needle else runs


def print_window_header(window: list[Run], title: str, args: argparse.Namespace) -> None:
    start, end = window[0].when, window[-1].when
    scenarios = len({r.scenario for r in window})
    print()
    print(t("window.header", title=title) + (" · Aimbeast" if args.source == "aimbeast" else ""))
    if args.days:
        print(t("window.range_days", start=start.strftime("%d.%m"), end=end.strftime("%d.%m"),
                runs=len(window), scenarios=scenarios, sessions=len(split_sessions(window))))
    else:
        print(t("window.range_session", start=start.strftime("%d.%m %H:%M"),
                end=end.strftime("%H:%M"), runs=len(window), scenarios=scenarios,
                minutes=round((end - start).total_seconds() / 60)))
    print()


# ── бенчмарки ────────────────────────────────────────────────────────────────

def bench_list() -> list[tuple[int, str]]:
    return kovaaks_api.load_bench_list(config.benchmarks_path()) or [DEFAULT_BENCH]


def bench_choice(bench_id: int | None) -> tuple[int, str]:
    """Какой бенчмарк показать в --bench: явный id или первый из списка."""
    listed = bench_list()
    if bench_id is None:
        return listed[0]
    return bench_id, dict(listed).get(bench_id, t("bench.default_name", id=bench_id))


def require_steam_id(cfg: config.Config) -> str:
    if not cfg.steam_id:
        raise SystemExit(t("config.need", key="steam_id"))
    return cfg.steam_id


def print_catalog(cfg: config.Config, query: str) -> None:
    if not cfg.kovaaks_user:
        raise SystemExit(t("config.need", key="kovaaks_user"))
    try:
        items = kovaaks_api.fetch_catalog(cfg.kovaaks_user)
    except kovaaks_api.ApiError as exc:
        raise SystemExit(t("catalog.failed", error=exc)) from None
    needle = query.lower()
    found = [b for b in items if b.get("type") == "benchmark"
             and needle in str(b.get("benchmarkName", "")).lower()]
    ranked = sorted(found, key=lambda b: (b.get("rankName") == "No Rank", b.get("benchmarkId", 0)))
    print()
    print("%6s  %-44s %s" % ("id", t("catalog.name"), t("catalog.rank")))
    for b in ranked:
        rank = "—" if b.get("rankName") == "No Rank" else b.get("rankName")
        print("%6s  %-44s %s" % (b.get("benchmarkId"), str(b.get("benchmarkName", ""))[:44].strip(), rank))
    print()
    print("  " + t("catalog.footer", n=len(ranked), total=len(items), file=config.benchmarks_path()))


# ── дашборд ──────────────────────────────────────────────────────────────────

def kovaaks_source(cfg: config.Config, args: argparse.Namespace, changes: list,
                   now: datetime) -> dict | None:
    if not cfg.kovaaks_dir or not os.path.isdir(cfg.kovaaks_dir):
        return None
    runs = load_kovaaks(cfg.kovaaks_dir)
    if not runs:
        return None
    benches = ([] if args.no_bench or not cfg.steam_id
               else dashboard.benches_payload(runs, bench_list(), cfg.steam_id, now))
    return dashboard.source_payload("KovaaK's", runs, changes, now, {"benches": benches})


def aimbeast_source(cfg: config.Config, changes: list, now: datetime) -> dict | None:
    if not cfg.aimbeast_dir or not os.path.isdir(cfg.aimbeast_dir):
        return None
    runs = load_aimbeast_checked(cfg.aimbeast_dir, cfg.steam_log)
    if not runs:
        return None
    extra = {"config": aimbeast.read_config(cfg.aimbeast_dir), "note": "aimbeast_note"}
    tagged = {name: "Ranked" for name in aimbeast.ranked_scenarios(cfg.aimbeast_dir)}
    return dashboard.source_payload("Aimbeast", runs, changes, now, extra, tagged)


def build_dashboard(cfg: config.Config, args: argparse.Namespace, changes: list) -> str:
    now = datetime.now()
    sources = {key: value for key, value in (
        ("kovaaks", kovaaks_source(cfg, args, changes, now)),
        ("aimbeast", aimbeast_source(cfg, changes, now))) if value}
    if not sources:
        raise SystemExit(t("dash.no_sources"))
    path = dashboard.write_dashboard(sources, changes, cfg.test_date or None,
                                     args.out or config.dashboard_path(cfg))
    print(t("dash.saved", path=path))
    if not args.no_open:
        dashboard.open_in_browser(path)
    return path


# ── настройки ────────────────────────────────────────────────────────────────

def print_config(cfg: config.Config) -> None:
    print()
    print(t("config.title", path=config.config_path()))
    for key, value in vars(cfg).items():
        print("  %-14s %s" % (key, value or "—"))
    print()
    print("  " + t("config.files", changes=config.changes_path(), benches=config.benchmarks_path()))
    print("  " + t("config.set_hint"))
    missing = [k for k in ("kovaaks_dir", "steam_id") if not getattr(cfg, k)]
    if missing:
        print("  !! " + t("config.missing", keys=", ".join(missing)))
    print()


def run_setup(cfg: config.Config) -> config.Config:
    """Повторный автопоиск: пустые поля заполняются, заполненные остаются."""
    updated = config.discover(cfg)
    if not updated.kovaaks_user and sys.stdin.isatty():
        name = input(t("setup.ask_user")).strip()
        if name:
            updated = config.set_value(updated, "kovaaks_user", name)
    config.save(updated, config.config_path())
    return updated


def apply_set(cfg: config.Config, pairs: list[str]) -> config.Config:
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(t("config.bad_pair", pair=pair))
        key, value = pair.split("=", 1)
        cfg = config.set_value(cfg, key.strip(), value.strip())
    config.save(cfg, config.config_path())
    return cfg


# ── запуск ───────────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="aim-telemetry", description=t("cli.description"))
    ap.add_argument("--version", action="version", version="%(prog)s " + __version__)
    ap.add_argument("--source", choices=("kovaaks", "aimbeast"), default="kovaaks",
                    help=t("cli.source"))
    ap.add_argument("--days", type=int, help=t("cli.days"))
    ap.add_argument("--session", type=int, default=1, help=t("cli.session"))
    ap.add_argument("--scenario", help=t("cli.scenario"))
    ap.add_argument("--top", type=int, default=5, help=t("cli.top"))
    ap.add_argument("--dir", help=t("cli.dir"))
    ap.add_argument("--bench", action="store_true", help=t("cli.bench"))
    ap.add_argument("--bench-id", type=int, help=t("cli.bench_id"))
    ap.add_argument("--list-benchmarks", nargs="?", const="", metavar="QUERY", help=t("cli.list"))
    ap.add_argument("--changes", action="store_true", help=t("cli.changes"))
    ap.add_argument("--dashboard", action="store_true", help=t("cli.dashboard"))
    ap.add_argument("--out", help=t("cli.out"))
    ap.add_argument("--no-open", action="store_true", help=t("cli.no_open"))
    ap.add_argument("--no-bench", action="store_true", help=t("cli.no_bench"))
    ap.add_argument("--no-cache", action="store_true", help=t("cli.no_cache"))
    ap.add_argument("--lang", choices=LANGS, help=t("cli.lang"))
    ap.add_argument("--setup", action="store_true", help=t("cli.setup"))
    ap.add_argument("--set", nargs="+", metavar="KEY=VALUE", help=t("cli.set"))
    ap.add_argument("--config", action="store_true", help=t("cli.config"))
    return ap.parse_args(argv)


def lang_from_argv(argv: list[str]) -> str | None:
    """Язык нужен до разбора аргументов — на нём написана справка."""
    for i, arg in enumerate(argv):
        if arg == "--lang" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--lang="):
            return arg.split("=", 1)[1]
    return None


def session_report(cfg: config.Config, args: argparse.Namespace, changes: list) -> None:
    runs = load_source(cfg, args)
    if args.bench:
        bench_id, name = bench_choice(args.bench_id)
        bench.print_bench(runs, bench_id, name, require_steam_id(cfg), args.top)
        return
    if args.changes:
        journal.print_changes(filter_scenario(runs, args.scenario), changes, config.changes_path())
        return

    window, title = pick_window(runs, args.days, args.session)
    window = filter_scenario(window, args.scenario)
    if not window:
        raise SystemExit(t("window.no_match", needle=args.scenario))
    change = journal.last_change(changes, window[0].when)
    cutoff = change.when if change else None
    baselines, excluded = build_baselines(runs, window, cutoff)

    print_window_header(window, title, args)
    if args.source == "aimbeast":
        print_aimbeast_environment(args.dir)
    else:
        print_environment(window, excluded)
    print_change_note(change, baselines, window[-1].when)
    table = print_scenarios(window, runs, baselines, cutoff)
    print_shape(window, baselines, aggregate=bool(args.days))
    print_todo(table, args.top)
    print_legend()


def double_clicked(argv: list[str]) -> bool:
    """Собранный .exe без аргументов: человек кликнул по файлу, консоль ему не нужна."""
    return getattr(sys, "frozen", False) and not argv


def run(argv: list[str]) -> None:
    cfg, created = config.ensure()
    set_lang(lang_from_argv(argv) or cfg.lang)
    if double_clicked(argv):
        argv = ["--dashboard"]
    args = parse_args(argv)
    kovaaks_api.set_cache_dir(None if args.no_cache else config.cache_dir())
    if created:
        print(t("setup.first_run"))
        if not (args.set or args.setup or args.config):   # эти команды сами покажут настройки
            print_config(cfg)

    if args.set:
        cfg = apply_set(cfg, args.set)
        print_config(cfg)
        return
    if args.setup:
        print_config(run_setup(cfg))
        return
    if args.config:
        print_config(cfg)
        return
    if args.list_benchmarks is not None:
        print_catalog(cfg, args.list_benchmarks)
        return
    changes = journal.load_changes(config.changes_path())
    if args.dashboard:
        build_dashboard(cfg, args, changes)
        return
    session_report(cfg, args, changes)


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    for stream in (sys.stdout, sys.stderr):
        # консоль Windows по умолчанию в cp1251/cp866 — кириллица и «·» без этого падают
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if not double_clicked(argv):
        run(argv)
        return
    # двойной клик: окно закроется сразу после выхода — сначала показать, что случилось
    try:
        run(argv)
    except SystemExit as exc:
        if exc.code not in (None, 0):
            print("\n" + str(exc.code), file=sys.stderr)
    except Exception:   # noqa: BLE001 — человеку без консоли нужен текст ошибки, а не мигнувшее окно
        traceback.print_exc()
    input("\n" + t("exe.press_enter"))
