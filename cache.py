from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from collections.abc import Iterator
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
            "SELECT file_size, modified_time, category FROM file_cache WHERE file_path = ?",
            (file_path,),
        ).fetchone()
        if not row:
            return False
        # 未分类文件即使内容未变化，也需要继续进入分类流程，避免永久卡在未分类状态。
        has_category = bool((row["category"] or "").strip())
        return row["file_size"] == file_size and row["modified_time"] == modified_time and has_category

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

    def upsert_files_bulk(self, rows: list[tuple[str, int, float]]) -> int:
        if not rows:
            return 0
        now = datetime.now().isoformat(timespec="seconds")
        with self.conn:
            self.conn.executemany(
                """
                INSERT INTO file_cache (file_path, file_size, modified_time, category, brief, summary, processed_at)
                VALUES (?, ?, ?, NULL, NULL, NULL, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    file_size = excluded.file_size,
                    modified_time = excluded.modified_time,
                    category = file_cache.category,
                    brief = file_cache.brief,
                    summary = file_cache.summary,
                    processed_at = excluded.processed_at
                """,
                [(file_path, file_size, modified_time, now) for file_path, file_size, modified_time in rows],
            )
        return len(rows)

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

    def update_categories_bulk(self, rows: list[tuple[str, str, str | None]]) -> int:
        if not rows:
            return 0
        now = datetime.now().isoformat(timespec="seconds")
        with self.conn:
            self.conn.executemany(
                """
                UPDATE file_cache
                SET category = ?, brief = COALESCE(?, brief), processed_at = ?
                WHERE file_path = ?
                """,
                [(category, brief, now, file_path) for file_path, category, brief in rows],
            )
        return len(rows)

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

    def clear_summaries_bulk(self, file_paths: list[str]) -> int:
        if not file_paths:
            return 0
        now = datetime.now().isoformat(timespec="seconds")
        with self.conn:
            for chunk in self._chunked(file_paths, 500):
                placeholders = ",".join("?" for _ in chunk)
                self.conn.execute(
                    f"""
                    UPDATE file_cache
                    SET summary = NULL, processed_at = ?
                    WHERE file_path IN ({placeholders})
                    """,
                    (now, *chunk),
                )
        return len(file_paths)

    @staticmethod
    def _chunked(items: list[str], size: int) -> Iterator[list[str]]:
        for index in range(0, len(items), size):
            yield items[index : index + size]

    def delete_absent_files(self, existing_paths: set[str]) -> int:
        cached_rows = self.conn.execute("SELECT file_path FROM file_cache").fetchall()
        if not cached_rows:
            return 0

        stale_paths = [row["file_path"] for row in cached_rows if row["file_path"] not in existing_paths]
        if not stale_paths:
            return 0

        deleted = 0
        with self.conn:
            for chunk in self._chunked(stale_paths, 500):
                placeholders = ",".join("?" for _ in chunk)
                cursor = self.conn.execute(
                    f"DELETE FROM file_cache WHERE file_path IN ({placeholders})",
                    tuple(chunk),
                )
                deleted += max(cursor.rowcount, 0)
        return deleted

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

    def filter_paths_with_category(self, file_paths: list[str]) -> list[str]:
        if not file_paths:
            return []

        matched: list[str] = []
        with self.conn:
            for chunk in self._chunked(file_paths, 500):
                placeholders = ",".join("?" for _ in chunk)
                rows = self.conn.execute(
                    f"""
                    SELECT file_path
                    FROM file_cache
                    WHERE file_path IN ({placeholders})
                    AND category IS NOT NULL
                    AND TRIM(category) != ''
                    ORDER BY file_path
                    """,
                    tuple(chunk),
                ).fetchall()
                matched.extend(row["file_path"] for row in rows)
        return matched

    def index_by_path(self) -> dict[str, CacheRecord]:
        rows = self.conn.execute("SELECT * FROM file_cache").fetchall()
        return {
            row["file_path"]: CacheRecord(**dict(row))
            for row in rows
        }

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
