"""Optional local history. Store the full observation without credentials."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .core import RankResult


def save_result(path: str, result: RankResult) -> None:
    with closing(sqlite3.connect(Path(path).expanduser())) as connection, connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS rank_checks (
                id INTEGER PRIMARY KEY,
                checked_at TEXT NOT NULL,
                domain TEXT NOT NULL,
                query TEXT NOT NULL,
                status TEXT NOT NULL,
                rank INTEGER,
                result_json TEXT NOT NULL
            )
        """)
        connection.execute(
            "INSERT INTO rank_checks (checked_at, domain, query, status, rank, result_json) VALUES (?, ?, ?, ?, ?, ?)",
            (
                result.checked_at,
                result.config.domain,
                result.config.query,
                result.status,
                result.rank,
                json.dumps(result.to_dict(), ensure_ascii=False),
            ),
        )
