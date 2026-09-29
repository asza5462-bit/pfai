"""Cloud hub for Windows MT5/Exness agent — real execution off Linux Render."""
from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path

from goldbot.config import settings

def _exness_servers() -> list[str]:
    """Generate common Exness MT5 trial/real server names (incl. Trial15+)."""
    out: list[str] = ["Exness-MT5Trial"]
    out.extend(f"Exness-MT5Trial{i}" for i in range(2, 31))
    out.append("Exness-MT5Real")
    out.extend(f"Exness-MT5Real{i}" for i in range(2, 61))
    return out


EXNESS_SERVERS = _exness_servers()


class RemoteHub:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (settings.data_dir / "bridge_hub.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        return c

    def _init(self) -> None:
        with self._conn() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS agents (
                  bridge_token TEXT PRIMARY KEY,
                  user_id INTEGER NOT NULL,
                  created_at REAL NOT NULL,
                  last_seen REAL DEFAULT 0,
                  online INTEGER DEFAULT 0,
                  agent_info TEXT DEFAULT '{}',
                  account_snap TEXT DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS commands (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  bridge_token TEXT NOT NULL,
                  kind TEXT NOT NULL,
                  payload TEXT NOT NULL,
                  status TEXT NOT NULL DEFAULT 'queued',
                  created_at REAL NOT NULL,
                  updated_at REAL NOT NULL,
                  result TEXT DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_cmd_token_status ON commands(bridge_token, status);
                """
            )

    def issue_token(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock, self._conn() as c:
            # revoke previous tokens for user
            c.execute("DELETE FROM agents WHERE user_id=?", (user_id,))
            c.execute(
                "INSERT INTO agents(bridge_token, user_id, created_at, last_seen, online) VALUES (?,?,?,?,0)",
                (token, user_id, now, 0),
            )
        return token

    def token_for_user(self, user_id: int) -> str | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT bridge_token FROM agents WHERE user_id=? ORDER BY created_at DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        return row["bridge_token"] if row else None

    def resolve(self, token: str | None) -> dict | None:
        if not token:
            return None
        with self._conn() as c:
            row = c.execute("SELECT * FROM agents WHERE bridge_token=?", (token,)).fetchone()
        return dict(row) if row else None

    def heartbeat(self, token: str, info: dict | None = None, account: dict | None = None) -> dict:
        now = time.time()
        with self._lock, self._conn() as c:
            row = c.execute("SELECT * FROM agents WHERE bridge_token=?", (token,)).fetchone()
            if not row:
                return {"ok": False, "error": "invalid_bridge_token"}
            c.execute(
                """UPDATE agents SET last_seen=?, online=1, agent_info=?, account_snap=?
                   WHERE bridge_token=?""",
                (
                    now,
                    json.dumps(info or {}, ensure_ascii=False),
                    json.dumps(account or {}, ensure_ascii=False),
                    token,
                ),
            )
        return {"ok": True, "server_time": now}

    def is_online(self, user_id: int, max_age: float = 20.0) -> bool:
        with self._conn() as c:
            row = c.execute(
                "SELECT last_seen, online FROM agents WHERE user_id=? ORDER BY last_seen DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        if not row:
            return False
        return bool(row["online"]) and (time.time() - float(row["last_seen"] or 0)) <= max_age

    def status_for_user(self, user_id: int) -> dict:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM agents WHERE user_id=? ORDER BY created_at DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        if not row:
            return {
                "linked": False,
                "online": False,
                "bridge_token_issued": False,
                "account": {},
                "detail": "لم يُربط وكيل MT5 بعد",
            }
        age = time.time() - float(row["last_seen"] or 0)
        online = bool(row["online"]) and age <= 20
        account = json.loads(row["account_snap"] or "{}")
        info = json.loads(row["agent_info"] or "{}")
        return {
            "linked": True,
            "online": online,
            "bridge_token_issued": True,
            "last_seen_age_sec": round(age, 1) if row["last_seen"] else None,
            "account": account,
            "agent": info,
            "detail": "وكيل MT5 متصل — التنفيذ على Exness" if online else "بانتظار تشغيل وكيل Windows MT5",
        }

    def enqueue(self, user_id: int, kind: str, payload: dict) -> dict:
        token = self.token_for_user(user_id)
        if not token:
            return {"ok": False, "error": "no_bridge_token"}
        if not self.is_online(user_id):
            return {"ok": False, "error": "bridge_offline", "detail": "شغّل وكيل AURUM على Windows مع MT5"}
        now = time.time()
        with self._lock, self._conn() as c:
            cur = c.execute(
                """INSERT INTO commands(bridge_token, kind, payload, status, created_at, updated_at)
                   VALUES (?,?,?,'queued',?,?)""",
                (token, kind, json.dumps(payload, ensure_ascii=False), now, now),
            )
            cmd_id = int(cur.lastrowid)
        return {"ok": True, "command_id": cmd_id}

    def poll_commands(self, token: str, limit: int = 10) -> list[dict]:
        self.heartbeat(token)
        with self._lock, self._conn() as c:
            rows = c.execute(
                """SELECT id, kind, payload, created_at FROM commands
                   WHERE bridge_token=? AND status='queued' ORDER BY id ASC LIMIT ?""",
                (token, limit),
            ).fetchall()
            out = []
            now = time.time()
            for r in rows:
                c.execute(
                    "UPDATE commands SET status='sent', updated_at=? WHERE id=?",
                    (now, r["id"]),
                )
                out.append(
                    {
                        "id": int(r["id"]),
                        "kind": r["kind"],
                        "payload": json.loads(r["payload"]),
                        "created_at": r["created_at"],
                    }
                )
        return out

    def complete_command(self, token: str, command_id: int, result: dict) -> dict:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT id FROM commands WHERE id=? AND bridge_token=?",
                (command_id, token),
            ).fetchone()
            if not row:
                return {"ok": False, "error": "command_not_found"}
            c.execute(
                "UPDATE commands SET status=?, result=?, updated_at=? WHERE id=?",
                (
                    "done" if result.get("ok") else "failed",
                    json.dumps(result, ensure_ascii=False),
                    time.time(),
                    command_id,
                ),
            )
        return {"ok": True}

    def wait_result(self, command_id: int, timeout: float = 12.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._conn() as c:
                row = c.execute("SELECT status, result FROM commands WHERE id=?", (command_id,)).fetchone()
            if row and row["status"] in {"done", "failed"}:
                return json.loads(row["result"] or "{}")
            time.sleep(0.25)
        return {"ok": False, "error": "bridge_timeout"}


hub = RemoteHub()
