"""Shared SQLite connection hardening (WAL + busy timeout)."""
from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(path: Path | str, *, timeout: float = 30.0) -> sqlite3.Connection:
    c = sqlite3.connect(str(path), timeout=timeout)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
        c.execute("PRAGMA temp_store=MEMORY")
    except Exception:
        pass
    return c
