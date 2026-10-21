"""Persistência SQLite: tabelas items, history e watchlist.

Todo acesso acontece na thread principal (os workers avisam por signals).
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id   INTEGER REFERENCES items(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL DEFAULT 'video',      -- video | group
    group_kind  TEXT DEFAULT '',                    -- playlist | mix
    group_ref   TEXT DEFAULT '',                    -- URL usada em "Carregar mais"
    video_id    TEXT DEFAULT '',
    title       TEXT DEFAULT '',
    channel     TEXT DEFAULT '',
    duration    INTEGER DEFAULT 0,
    url         TEXT DEFAULT '',
    thumb       TEXT DEFAULT '',
    position    INTEGER DEFAULT 0,
    status      TEXT DEFAULT 'ready',
    output_path TEXT DEFAULT '',
    error       TEXT DEFAULT '',
    created_at  REAL DEFAULT (strftime('%s','now'))
);
CREATE INDEX IF NOT EXISTS idx_items_video  ON items(video_id);
CREATE INDEX IF NOT EXISTS idx_items_parent ON items(parent_id);

CREATE TABLE IF NOT EXISTS history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id    TEXT, title TEXT, fmt TEXT, quality TEXT, output_path TEXT,
    finished_at REAL DEFAULT (strftime('%s','now'))
);

CREATE TABLE IF NOT EXISTS watchlist (   -- reservado para futuras inscrições em canais/playlists
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE, title TEXT, created_at REAL DEFAULT (strftime('%s','now'))
);
"""

TRANSIENT = ("queued", "downloading", "converting", "analyzing")


SCHEMA_VERSION = 1
EXPECTED_COLS = {"id", "parent_id", "kind", "group_kind", "group_ref", "video_id", "title", "channel", "duration",
                 "url", "thumb", "position", "status", "output_path", "error"}


def _is_compatible(path: Path) -> bool:
    """False se já existe um library.db com outra estrutura (ex.: de uma versão/projeto anterior)."""
    if not Path(path).exists():
        return True
    try:
        con = sqlite3.connect(str(path))
        cols = {r[1] for r in con.execute("PRAGMA table_info(items)")}
        con.close()
    except sqlite3.Error:
        return False
    return not cols or EXPECTED_COLS <= cols


def _backup_incompatible(path: Path) -> None:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for suffix in ("", "-wal", "-shm"):
        f = Path(str(path) + suffix)
        if f.exists():
            try:
                f.rename(f.with_name(f"{f.name}.old-{stamp}"))
            except OSError:
                try:
                    f.unlink()
                except OSError:
                    pass


class Database:
    def __init__(self, path: Path):
        if not _is_compatible(path):
            _backup_incompatible(Path(path))  # mantém o arquivo antigo como backup e começa um banco novo
        self.conn = sqlite3.connect(str(path), isolation_level=None)  # autocommit
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")  # sem isso o ON DELETE CASCADE não funciona
        self.conn.executescript(SCHEMA)
        self.conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self.purge_orphans()

    @contextmanager
    def transaction(self):
        self.conn.execute("BEGIN")
        try:
            yield
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    def purge_orphans(self) -> None:
        self.conn.execute("DELETE FROM items WHERE parent_id IS NOT NULL AND parent_id NOT IN (SELECT id FROM items)")
        marks = ",".join("?" * len(TRANSIENT))
        self.conn.execute(f"UPDATE items SET status='ready' WHERE status IN ({marks})", TRANSIENT)

    def add_group(self, title: str, group_kind: str, group_ref: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO items(kind, group_kind, group_ref, title, status) VALUES('group', ?, ?, ?, '')",
            (group_kind, group_ref, title),
        )
        return int(cur.lastrowid)

    def add_video(self, e: dict, parent_id: int | None, status: str = "ready") -> int:
        cur = self.conn.execute(
            "INSERT INTO items(parent_id, kind, video_id, title, channel, duration, url, thumb, position, status) "
            "VALUES(?, 'video', ?, ?, ?, ?, ?, ?, ?, ?)",
            (parent_id, e.get("video_id", ""), e.get("title", ""), e.get("channel", ""),
             int(e.get("duration") or 0), e.get("url", ""), e.get("thumb", ""), int(e.get("index") or 0), status),
        )
        return int(cur.lastrowid)

    def set_status(self, item_id: int, status: str, output_path: str = "", error: str = "") -> None:
        self.conn.execute(
            "UPDATE items SET status=?, output_path=?, error=? WHERE id=?", (status, output_path, error, item_id)
        )

    def delete(self, item_id: int) -> None:
        self.conn.execute("DELETE FROM items WHERE id=?", (item_id,))

    def all_rows(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM items ORDER BY id").fetchall()

    def add_history(self, video_id: str, title: str, fmt: str, quality: str, path: str) -> None:
        self.conn.execute(
            "INSERT INTO history(video_id, title, fmt, quality, output_path) VALUES(?,?,?,?,?)",
            (video_id, title, fmt, quality, path),
        )

    def close(self) -> None:
        try:
            self.conn.close()
        except sqlite3.Error:
            pass
