"""Сборка одного .exe: uv run python scripts/build_exe.py → dist/aim-telemetry.exe"""

import os

import PyInstaller.__main__

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "src", "aim_telemetry", "web")

PyInstaller.__main__.run([
    os.path.join(ROOT, "scripts", "entry.py"),
    "--name", "aim-telemetry",
    "--onefile",
    "--console",                                  # отчёт печатается в консоль; двойной клик ждёт Enter
    "--paths", os.path.join(ROOT, "src"),
    "--add-data", "%s%saim_telemetry/web" % (WEB, os.pathsep),
    "--distpath", os.path.join(ROOT, "dist"),
    "--workpath", os.path.join(ROOT, "build"),
    "--specpath", os.path.join(ROOT, "build"),
    "--noconfirm",
    "--clean",
])
