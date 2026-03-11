from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class CacheRecord:
    file_path: str
    file_size: int
    modified_time: float
    category: str | None = None
    brief: str | None = None
    summary: str | None = None
    processed_at: str | None = None


class CacheDB:
    def __init__(self, db_path: str | Path = "cache.db") -> None:
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS file_cache (
                file_path TEXT PRIMARY KEY,
                file_size INTEGER NOT NULL,
                modified_time REAL NOT NULL,
                category TEXT,
                brief TEXT,
                summary TEXT,
                processed_at TEXT NOT NULL
            )
            """
        )
        self.conn.commit()
        self._migrate_add_brief()

    def _migrate_add_brief(self) -> None:
        columns = [
            row[1]
            for row in self.conn.execute("PRAGMA table_info(file_cache)").fetchall()
        ]
        if "brief" not in columns:
            self.conn.execute("ALTER TABLE file_cache ADD COLUMN brief TEXT")
            self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def get(self, file_path: str) -> CacheRecord | None:
        row = self.conn.execute(
            "SELECT * FROM file_cache WHERE file_path = ?",
            (file_path,),
        ).fetchone()
        if not row:
            return None
        return CacheRecord(**dict(row))

    def is_unchanged(self, file_path: str, file_size: int, modified_time: float) -> bool:
        row = self.conn.execute(
            "SELECT file_size, modified_time FROM file_cache WHERE file_path = ?",
            (file_path,),
        ).fetchone()
        if not row:
            return False
        return row["file_size"] == file_size and row["modified_time"] == modified_time

    def upsert_file(
        self,
        file_path: str,
        file_size: int,
        modified_time: float,
        category: str | None = None,
        brief: str | None = None,
        summary: str | None = None,
    ) -> None:
        processed_at = datetime.now().isoformat(timespec="seconds")
        self.conn.execute(
            """
            INSERT INTO file_cache (file_path, file_size, modified_time, category, brief, summary, processed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_path) DO UPDATE SET
                file_size = excluded.file_size,
                modified_time = excluded.modified_time,
                category = COALESCE(excluded.category, file_cache.category),
                brief = COALESCE(excluded.brief, file_cache.brief),
                summary = COALESCE(excluded.summary, file_cache.summary),
                processed_at = excluded.processed_at
            """,
            (file_path, file_size, modified_time, category, brief, summary, processed_at),
        )
        self.conn.commit()

    def update_category(self, file_path: str, category: str, brief: str | None = None) -> None:
        if brief:
            self.conn.execute(
                """
                UPDATE file_cache
                SET category = ?, brief = ?, processed_at = ?
                WHERE file_path = ?
                """,
                (category, brief, datetime.now().isoformat(timespec="seconds"), file_path),
            )
        else:
            self.conn.execute(
                """
                UPDATE file_cache
                SET category = ?, processed_at = ?
                WHERE file_path = ?
                """,
                (category, datetime.now().isoformat(timespec="seconds"), file_path),
            )
        self.conn.commit()

    def update_summary(self, file_path: str, summary: str) -> None:
        self.conn.execute(
            """
            UPDATE file_cache
            SET summary = ?, processed_at = ?
            WHERE file_path = ?
            """,
            (summary, datetime.now().isoformat(timespec="seconds"), file_path),
        )
        self.conn.commit()

    def list_all(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM file_cache ORDER BY category IS NULL, category, file_path"
        ).fetchall()
        return [dict(row) for row in rows]

    def list_by_category(self, category: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM file_cache WHERE category = ? ORDER BY file_path",
            (category,),
        ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        total = self.conn.execute("SELECT COUNT(*) AS c FROM file_cache").fetchone()["c"]
        with_summary = self.conn.execute(
            "SELECT COUNT(*) AS c FROM file_cache WHERE summary IS NOT NULL AND summary != ''"
        ).fetchone()["c"]
        categorized = self.conn.execute(
            "SELECT COUNT(*) AS c FROM file_cache WHERE category IS NOT NULL AND category != ''"
        ).fetchone()["c"]
        categories = self.conn.execute(
            """
            SELECT COALESCE(category, '未分类') AS category, COUNT(*) AS count
            FROM file_cache
            GROUP BY COALESCE(category, '未分类')
            ORDER BY count DESC, category
            """
        ).fetchall()
        return {
            "total_files": total,
            "categorized_files": categorized,
            "summarized_files": with_summary,
            "categories": [dict(row) for row in categories],
        }
