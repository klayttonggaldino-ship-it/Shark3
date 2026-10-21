# -*- mode: python ; coding: utf-8 -*-
# PyInstaller (modo onedir). Gere com:  pyinstaller build.spec --noconfirm --clean
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

APP_NAME = "Shark3"  # mantenha igual a app/paths.py e installer.iss

datas = [("assets", "assets")]
binaries = []
hiddenimports = ["mutagen", "mutagen.mp4", "mutagen.oggopus", "mutagen.oggvorbis", "mutagen.flac", "mutagen.id3"]

# FFmpeg embutido (imageio-ffmpeg) e scripts de desafio do YouTube (yt-dlp-ejs) precisam ir junto
for pkg in ("imageio_ffmpeg", "yt_dlp_ejs", "certifi"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
hiddenimports += collect_submodules("yt_dlp")

# Deno (runtime JavaScript do yt-dlp) — baixado por tools/get_deno.ps1
if Path("bin/deno.exe").exists():
    datas.append(("bin/deno.exe", "bin"))

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
              "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtCharts"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,
    icon="assets/icon.ico",
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=APP_NAME)
