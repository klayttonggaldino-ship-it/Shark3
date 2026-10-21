"""Caminhos e constantes globais.

Funciona tanto rodando do código-fonte quanto dentro do EXE gerado pelo PyInstaller
(modo onedir). Nunca use sys.executable como comando de subprocesso no EXE
(ele aponta para o próprio programa e causaria múltiplas aberturas).
"""
from __future__ import annotations

import sys
from pathlib import Path

APP_NAME = "Shark3"  # nome provisório: troque aqui, em build.spec e em installer.iss
APP_VERSION = "1.0.0"

FROZEN = bool(getattr(sys, "frozen", False))

if FROZEN:
    BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))  # pasta _internal
    EXE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    EXE_DIR = BASE_DIR

ASSETS_DIR = BASE_DIR / "assets"
BIN_DIRS = [EXE_DIR / "bin", BASE_DIR / "bin"]  # deno.exe / ffmpeg.exe opcionais

DATA_DIR = Path.home() / ".ytmusic_downloader"
CONFIG_PATH = DATA_DIR / "config.json"
DB_PATH = DATA_DIR / "library.db"
LOG_PATH = DATA_DIR / "app.log"
UI_DIR = DATA_DIR / "ui"
TMP_DIR = DATA_DIR / "tmp"
