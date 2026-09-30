"""Где что лежит у Steam: корень, библиотеки игр, папки тренажёров, аккаунт.

Всё читается из файлов самого Steam и не требует прав администратора:
  * корень — из реестра (HKCU\\Software\\Valve\\Steam\\SteamPath) или стандартных путей;
  * библиотеки — steamapps/libraryfolders.vdf;
  * папка игры — appmanifest_<id>.acf → installdir;
  * аккаунт — config/loginusers.vdf, последний вошедший.
"""

import os
import re
import sys
from typing import NamedTuple

DEFAULT_ROOTS = (
    r"C:\Program Files (x86)\Steam",
    r"C:\Program Files\Steam",
    os.path.expanduser("~/.steam/steam"),
    os.path.expanduser("~/.local/share/Steam"),
)
TOKEN_RE = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])')
ESCAPE_RE = re.compile(r"\\(.)")


class SteamUser(NamedTuple):
    steam_id: str
    persona: str


# ── VDF ──────────────────────────────────────────────────────────────────────

def parse_vdf(text: str) -> dict:
    """Текстовый KeyValues Valve: "ключ" "значение" и "ключ" { ... }."""
    tokens = [(m.group(1), m.group(2)) for m in TOKEN_RE.finditer(text)]
    root: dict = {}
    stack = [root]
    key = None
    for value, brace in tokens:
        if brace == "{":
            child: dict = {}
            stack[-1][key if key is not None else ""] = child
            stack.append(child)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        elif key is None:
            key = unescape(value)
        else:
            stack[-1][key] = unescape(value)
            key = None
    return root


def unescape(value: str) -> str:
    """\\\\ → \\, \\" → " — так Valve экранирует пути Windows и кавычки в именах."""
    return ESCAPE_RE.sub(r"\1", value)


def read_vdf(path: str) -> dict:
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            return parse_vdf(fh.read())
    except OSError:
        return {}


# ── поиск ────────────────────────────────────────────────────────────────────

def registry_root() -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            return os.path.normpath(winreg.QueryValueEx(key, "SteamPath")[0])
    except OSError:
        return None


def steam_root() -> str | None:
    for candidate in (registry_root(), *DEFAULT_ROOTS):
        if candidate and os.path.isdir(os.path.join(candidate, "steamapps")):
            return candidate
    return None


def library_paths(root: str) -> list[str]:
    """Все библиотеки игр, начиная с самой папки Steam."""
    data = read_vdf(os.path.join(root, "steamapps", "libraryfolders.vdf"))
    folders = data.get("libraryfolders", {})
    paths = [root]
    for entry in folders.values() if isinstance(folders, dict) else []:
        path = entry.get("path") if isinstance(entry, dict) else entry
        if isinstance(path, str) and os.path.normpath(path) not in map(os.path.normpath, paths):
            paths.append(path)
    return [p for p in paths if os.path.isdir(os.path.join(p, "steamapps"))]


def app_dir(root: str, app_id: str) -> str | None:
    """Папка установленной игры по её Steam ID."""
    for library in library_paths(root):
        manifest = read_vdf(os.path.join(library, "steamapps", "appmanifest_%s.acf" % app_id))
        installdir = manifest.get("AppState", {}).get("installdir")
        if installdir:
            path = os.path.join(library, "steamapps", "common", installdir)
            if os.path.isdir(path):
                return path
    return None


def last_user(root: str) -> SteamUser | None:
    """Аккаунт, который входил последним: MostRecent, иначе самый свежий Timestamp."""
    users = read_vdf(os.path.join(root, "config", "loginusers.vdf")).get("users", {})
    if not isinstance(users, dict) or not users:
        return None

    def rank(item: tuple[str, dict]) -> tuple[int, int]:
        info = item[1] if isinstance(item[1], dict) else {}
        stamp = info.get("Timestamp", "0")
        return (info.get("MostRecent") == "1", int(stamp) if stamp.isdigit() else 0)

    steam_id, info = max(users.items(), key=rank)
    return SteamUser(steam_id, info.get("PersonaName", "") if isinstance(info, dict) else "")


def process_log(root: str) -> str | None:
    path = os.path.join(root, "logs", "gameprocess_log.txt")
    return path if os.path.exists(path) else None
