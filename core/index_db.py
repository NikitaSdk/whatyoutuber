"""Один SQLite-индекс на все каналы. Пишет только один поток за раз."""

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from core.lemma import lemmatize

_WRITE = threading.Lock()
_RANK = {"": 0, "subs_auto": 1, "subs_manual": 2, "asr_index": 3, "transcript": 4}

_SCHEMA = """
PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS videos (
    video_id    TEXT PRIMARY KEY,
    channel_id  TEXT NOT NULL,
    duration    REAL DEFAULT 0,
    status      TEXT DEFAULT 'pending',
    source      TEXT DEFAULT '',
    lang        TEXT DEFAULT '',
    indexed_at  TEXT DEFAULT '',
    error       TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS windows (
    id        INTEGER PRIMARY KEY,
    video_id  TEXT NOT NULL,
    start     INTEGER NOT NULL,
    kind      TEXT DEFAULT 'speech',
    text      TEXT NOT NULL,
    lemmas    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS windows_video ON windows(video_id);
CREATE VIRTUAL TABLE IF NOT EXISTS windows_fts USING fts5(
    lemmas, content='windows', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
CREATE VIRTUAL TABLE IF NOT EXISTS meta_fts USING fts5(
    video_id UNINDEXED, title, description, tokenize='unicode61 remove_diacritics 2'
);
"""


def index_file(data_dir) -> Path:
    return Path(data_dir) / "index.sqlite"


class IndexDB:
    def __init__(self, path):
        self.path = str(path)

    def _connect(self):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        con.executescript(_SCHEMA)
        return con

    def statuses(self, video_ids: list) -> dict:
        if not video_ids:
            return {}
        con = self._connect()
        try:
            found = {}
            for offset in range(0, len(video_ids), 400):
                chunk = list(video_ids)[offset:offset + 400]
                marks = ",".join("?" for _ in chunk)
                rows = con.execute(f"SELECT video_id, status FROM videos WHERE video_id IN ({marks})", chunk)
                found.update({row["video_id"]: row["status"] for row in rows})
            return found
        finally:
            con.close()

    def counts(self, channel_id: str) -> dict:
        con = self._connect()
        try:
            rows = con.execute(
                "SELECT status, COUNT(*) AS n FROM videos WHERE channel_id = ? GROUP BY status",
                (channel_id,),
            )
            return {row["status"]: row["n"] for row in rows}
        finally:
            con.close()

    def no_text_total(self) -> int:
        con = self._connect()
        try:
            row = con.execute("SELECT COUNT(*) AS n FROM videos WHERE status = 'no_text'").fetchone()
            return int(row["n"] or 0)
        finally:
            con.close()

    def no_text_ids(self, channel_id: str) -> list:
        con = self._connect()
        try:
            rows = con.execute(
                "SELECT video_id FROM videos WHERE channel_id = ? AND status = 'no_text' ORDER BY video_id",
                (channel_id,),
            )
            return [row["video_id"] for row in rows]
        finally:
            con.close()

    def source_of(self, video_id: str) -> str:
        con = self._connect()
        try:
            row = con.execute("SELECT source FROM videos WHERE video_id = ?", (video_id,)).fetchone()
            return row["source"] if row else ""
        finally:
            con.close()

    def replace_video(self, video_id, channel_id, duration, windows, meta, source, lang, status="indexed") -> bool:
        """Переиндексировать видео. Более сильный источник не затирается слабым."""
        with _WRITE:
            con = self._connect()
            try:
                current = con.execute("SELECT source FROM videos WHERE video_id = ?", (video_id,)).fetchone()
                if current and _RANK.get(current["source"] or "", 0) > _RANK.get(source or "", 0):
                    return False
                self._wipe(con, video_id)
                for start, text, kind in windows:
                    lemmas = lemmatize(text)
                    if not (text or "").strip() or not lemmas:
                        continue
                    row = con.execute(
                        "INSERT INTO windows(video_id, start, kind, text, lemmas) VALUES(?,?,?,?,?)",
                        (video_id, int(start), kind or "speech", text, lemmas),
                    )
                    con.execute("INSERT INTO windows_fts(rowid, lemmas) VALUES(?, ?)", (row.lastrowid, lemmas))
                title, description, tags = meta
                con.execute(
                    "INSERT INTO meta_fts(video_id, title, description) VALUES(?,?,?)",
                    (video_id, lemmatize(title or ""), lemmatize(f"{description or ''} {tags or ''}")),
                )
                con.execute(
                    """
                    INSERT INTO videos(video_id, channel_id, duration, status, source, lang, indexed_at, error)
                    VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(video_id) DO UPDATE SET
                        channel_id=excluded.channel_id,
                        duration=CASE WHEN excluded.duration > 0 THEN excluded.duration ELSE videos.duration END,
                        status=excluded.status,
                        source=excluded.source,
                        lang=excluded.lang,
                        indexed_at=excluded.indexed_at,
                        error=''
                    """,
                    (video_id, channel_id, float(duration or 0), status, source or "", lang or "",
                     datetime.now().isoformat(timespec="seconds"), ""),
                )
                con.commit()
                return True
            except Exception:
                con.rollback()
                raise
            finally:
                con.close()

    def mark(self, video_id, channel_id, status, error="", duration=0, meta=None) -> None:
        with _WRITE:
            con = self._connect()
            try:
                if meta:
                    self._wipe(con, video_id)
                    title, description, tags = meta
                    con.execute(
                        "INSERT INTO meta_fts(video_id, title, description) VALUES(?,?,?)",
                        (video_id, lemmatize(title or ""), lemmatize(f"{description or ''} {tags or ''}")),
                    )
                con.execute(
                    """
                    INSERT INTO videos(video_id, channel_id, duration, status, source, lang, indexed_at, error)
                    VALUES(?,?,?,?, '', '', ?, ?)
                    ON CONFLICT(video_id) DO UPDATE SET
                        status=excluded.status,
                        error=excluded.error,
                        indexed_at=excluded.indexed_at,
                        duration=CASE WHEN excluded.duration > 0 THEN excluded.duration ELSE videos.duration END
                    """,
                    (video_id, channel_id, float(duration or 0), status,
                     datetime.now().isoformat(timespec="seconds"), error or ""),
                )
                con.commit()
            except Exception:
                con.rollback()
                raise
            finally:
                con.close()

    def _wipe(self, con, video_id: str) -> None:
        rows = con.execute("SELECT id, lemmas FROM windows WHERE video_id = ?", (video_id,)).fetchall()
        for row in rows:
            con.execute(
                "INSERT INTO windows_fts(windows_fts, rowid, lemmas) VALUES('delete', ?, ?)",
                (row["id"], row["lemmas"]),
            )
        con.execute("DELETE FROM windows WHERE video_id = ?", (video_id,))
        con.execute("DELETE FROM meta_fts WHERE video_id = ?", (video_id,))
