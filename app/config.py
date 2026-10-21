"""Configurações do usuário (JSON em ~/.ytmusic_downloader/config.json)."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

from .paths import APP_NAME, CONFIG_PATH, DATA_DIR

# Seis bandas do equalizador paramétrico (frequências da especificação).
DEFAULT_EQ_BANDS = [
    {"type": "lowshelf", "freq": 60.0, "gain": 0.0, "q": 0.71, "on": True},
    {"type": "bell", "freq": 170.0, "gain": 0.0, "q": 1.0, "on": True},
    {"type": "bell", "freq": 350.0, "gain": 0.0, "q": 1.0, "on": True},
    {"type": "bell", "freq": 1000.0, "gain": 0.0, "q": 1.0, "on": True},
    {"type": "bell", "freq": 3500.0, "gain": 0.0, "q": 1.0, "on": True},
    {"type": "highshelf", "freq": 10000.0, "gain": 0.0, "q": 0.71, "on": True},
]

DEFAULTS: dict = {
    "download_dir": str(Path.home() / "Music" / APP_NAME),
    "format": "mp3",           # mp3 | m4a | opus | ogg | flac | wav | best
    "quality": "192",          # kbps, "v0/v2/v4" (MP3 VBR) ou "" (sem perdas/original)
    "source": "best",          # best | m4a | opus  (preferência do áudio de origem)
    "concurrency": 2,
    "auto_start": True,
    "existing_file_action": "ask",   # ask | skip | replace | rename
    "rate_limit": "",
    "retries": 5,
    "organize": "none",        # none | playlist | channel
    "number_prefix": True,
    "name_style": "title",     # title | artist_title
    "embed_metadata": True,
    "album_from_playlist": True,
    "embed_thumbnail": True,
    "square_cover": True,
    "normalize": False,
    "eq_enabled": False,
    "eq_bands": DEFAULT_EQ_BANDS,
    "cookies_browser": "",
    "cookies_file": "",
    "proxy": "",
    "js_runtime_path": "",
    "allow_remote_components": False,
}


class Config:
    def __init__(self, path: Path = CONFIG_PATH):
        self.path = Path(path)
        self.data: dict = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        for key, default in DEFAULTS.items():
            if key in raw and isinstance(raw[key], type(default)):
                self.data[key] = raw[key]
        bands = self.data.get("eq_bands")
        if not (isinstance(bands, list) and len(bands) == 6 and all(isinstance(b, dict) for b in bands)):
            self.data["eq_bands"] = copy.deepcopy(DEFAULT_EQ_BANDS)

    def save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value) -> None:
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, default)

    def snapshot(self) -> dict:
        """Cópia independente para uma tarefa (mudar as opções não afeta downloads em curso)."""
        return copy.deepcopy(self.data)
