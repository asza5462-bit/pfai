"""Persistent desk state (SQLite)."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from goldbot.config import settings


class DeskStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (settings.data_dir / "desk.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def _init(self) -> None:
        with self._conn() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  ts REAL NOT NULL,
                  kind TEXT NOT NULL,
                  payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trades (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  ts REAL NOT NULL,
                  ticket INTEGER,
                  side TEXT,
                  lot REAL,
                  entry REAL,
                  sl REAL,
                  tp REAL,
                  status TEXT,
                  pnl REAL DEFAULT 0,
                  mode TEXT,
                  meta TEXT
                );
                CREATE TABLE IF NOT EXISTS kv (
                  key TEXT PRIMARY KEY,
                  value TEXT NOT NULL
                );
                """
            )

    def log_event(self, kind: str, payload: dict) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO events(ts, kind, payload) VALUES (?,?,?)",
                (time.time(), kind, json.dumps(payload, ensure_ascii=False)),
            )

    def add_trade(self, trade: dict) -> int:
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO trades(ts, ticket, side, lot, entry, sl, tp, status, pnl, mode, meta)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    time.time(),
                    trade.get("ticket"),
                    trade.get("side"),
                    trade.get("lot"),
                    trade.get("price") or trade.get("entry"),
                    trade.get("sl"),
                    trade.get("tp"),
                    trade.get("status", "open"),
                    trade.get("pnl", 0.0),
                    trade.get("mode", "paper"),
                    json.dumps(trade.get("meta") or {}, ensure_ascii=False),
                ),
            )
            return int(cur.lastrowid)

    def recent_trades(self, limit: int = 50) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def open_trades(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM trades WHERE status='open' ORDER BY id ASC").fetchall()
        return [dict(r) for r in rows]

    def close_trade(self, trade_id: int, pnl: float, status: str = "closed") -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE trades SET status=?, pnl=? WHERE id=?",
                (status, float(pnl), int(trade_id)),
            )

    def update_trade(self, trade_id: int, **fields) -> None:
        allowed = {"sl", "tp", "lot", "status", "pnl", "meta", "entry"}
        cols = []
        vals = []
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k == "meta" and not isinstance(v, str):
                v = json.dumps(v, ensure_ascii=False)
            cols.append(f"{k}=?")
            vals.append(v)
        if not cols:
            return
        vals.append(int(trade_id))
        with self._conn() as c:
            c.execute(f"UPDATE trades SET {', '.join(cols)} WHERE id=?", vals)

    def recent_events(self, limit: int = 40) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d["payload"])
            out.append(d)
        return out

    def set_kv(self, key: str, value: dict | str | bool | float | int) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO kv(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )

    def get_kv(self, key: str, default=None):
        with self._conn() as c:
            row = c.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        return json.loads(row["value"])


store = DeskStore()
