"""Persistent desk state (SQLite)."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from goldbot.config import settings
from goldbot.util_sqlite import connect as sqlite_connect


class DeskStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (settings.data_dir / "desk.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _conn(self) -> sqlite3.Connection:
        return sqlite_connect(self.path, timeout=30.0)

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

    @staticmethod
    def _enrich_trade_row(row: dict) -> dict:
        """Surface position_id / order_id from meta for smart exits / closes."""
        out = dict(row)
        meta = out.get("meta")
        if isinstance(meta, str) and meta:
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        if not isinstance(meta, dict):
            meta = {}
        out["meta"] = meta
        if meta.get("position_id") and not out.get("position_id"):
            out["position_id"] = meta["position_id"]
        if meta.get("order_id") and not out.get("order_id"):
            out["order_id"] = meta["order_id"]
        if meta.get("execution") and not out.get("execution"):
            out["execution"] = meta["execution"]
        return out

    def add_trade(self, trade: dict) -> int:
        meta = dict(trade.get("meta") or {})
        # Persist broker ids inside meta (schema has no dedicated columns)
        for key in ("position_id", "order_id", "execution", "symbol", "string_code"):
            if trade.get(key) not in (None, ""):
                meta[key] = trade[key]
        # Prefer MetaApi positionId as the closable ticket
        ticket = trade.get("ticket")
        pos = trade.get("position_id") or meta.get("position_id")
        if pos not in (None, "", 0, "0"):
            try:
                ticket = int(pos)
            except (TypeError, ValueError):
                ticket = ticket or 0
            meta["position_id"] = str(pos)
        entry = trade.get("price") or trade.get("entry") or 0
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO trades(ts, ticket, side, lot, entry, sl, tp, status, pnl, mode, meta)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    time.time(),
                    ticket,
                    trade.get("side"),
                    trade.get("lot"),
                    entry,
                    trade.get("sl"),
                    trade.get("tp"),
                    trade.get("status", "open"),
                    trade.get("pnl", 0.0),
                    trade.get("mode", "paper"),
                    json.dumps(meta, ensure_ascii=False),
                ),
            )
            return int(cur.lastrowid)

    def recent_trades(self, limit: int = 50) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [self._enrich_trade_row(dict(r)) for r in rows]

    def open_trades(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM trades WHERE status='open' ORDER BY id ASC").fetchall()
        return [self._enrich_trade_row(dict(r)) for r in rows]

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
