"""Command Chat memory service — wraps existing MemoryStore + conversation SQLite.

Learning in phase-1 means durable memory / feedback / approved knowledge —
never automatic model-weight mutation.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .memory import MemoryStore

APPROVED_KINDS = {
    "preference",
    "decision",
    "approved_knowledge",
    "correction",
    "feedback",
    "conversation_note",
}


class CommandMemoryService:
    def __init__(self, memory: MemoryStore, chat_db_path: str = "data/command_chat.sqlite3"):
        self.memory = memory
        p = Path(chat_db_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(p, check_same_thread=False)
        self._lock = threading.RLock()
        with self._lock:
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                  id TEXT PRIMARY KEY,
                  title TEXT,
                  created_at TEXT,
                  updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS messages (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  conversation_id TEXT,
                  role TEXT,
                  content TEXT,
                  status TEXT,
                  meta_json TEXT,
                  created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS pending_actions (
                  id TEXT PRIMARY KEY,
                  conversation_id TEXT,
                  tool TEXT,
                  args_json TEXT,
                  reason TEXT,
                  status TEXT,
                  created_at TEXT,
                  resolved_at TEXT,
                  resolved_by TEXT
                );
                """
            )
            self.db.commit()

    # -- conversations -------------------------------------------------
    def create_conversation(self, title: str = "PFAI Command Chat") -> str:
        cid = uuid.uuid4().hex
        now = _now()
        with self._lock:
            self.db.execute(
                "INSERT INTO conversations(id,title,created_at,updated_at) VALUES(?,?,?,?)",
                (cid, title, now, now),
            )
            self.db.commit()
        return cid

    def list_conversations(self, limit: int = 30) -> list[dict]:
        with self._lock:
            rows = self.db.execute(
                "SELECT id,title,created_at,updated_at FROM conversations ORDER BY updated_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [dict(id=r[0], title=r[1], created_at=r[2], updated_at=r[3]) for r in rows]

    def ensure_conversation(self, conversation_id: str | None) -> str:
        if conversation_id:
            with self._lock:
                row = self.db.execute("SELECT id FROM conversations WHERE id=?", (conversation_id,)).fetchone()
            if row:
                return conversation_id
        return self.create_conversation()

    def add_message(self, conversation_id: str, role: str, content: str, status: str = "completed", meta: dict | None = None) -> int:
        now = _now()
        with self._lock:
            cur = self.db.execute(
                "INSERT INTO messages(conversation_id,role,content,status,meta_json,created_at) VALUES(?,?,?,?,?,?)",
                (conversation_id, role, content, status, json.dumps(meta or {}, ensure_ascii=False), now),
            )
            self.db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id))
            self.db.commit()
            return int(cur.lastrowid)

    def get_messages(self, conversation_id: str, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self.db.execute(
                "SELECT id,role,content,status,meta_json,created_at FROM messages WHERE conversation_id=? ORDER BY id ASC LIMIT ?",
                (conversation_id, int(limit)),
            ).fetchall()
        out = []
        for r in rows:
            try:
                meta = json.loads(r[4] or "{}")
            except json.JSONDecodeError:
                meta = {}
            out.append(dict(id=r[0], role=r[1], content=r[2], status=r[3], meta=meta, created_at=r[5]))
        return out

    def recent_dialog(self, conversation_id: str, limit: int = 8) -> list[dict]:
        msgs = self.get_messages(conversation_id)
        return msgs[-limit:]

    # -- pending approvals ---------------------------------------------
    def create_pending(self, conversation_id: str, tool: str, args: dict, reason: str) -> str:
        pid = uuid.uuid4().hex
        with self._lock:
            self.db.execute(
                "INSERT INTO pending_actions(id,conversation_id,tool,args_json,reason,status,created_at) VALUES(?,?,?,?,?,?,?)",
                (pid, conversation_id, tool, json.dumps(args or {}, ensure_ascii=False), reason, "waiting_for_approval", _now()),
            )
            self.db.commit()
        return pid

    def get_pending(self, pending_id: str) -> dict | None:
        with self._lock:
            row = self.db.execute(
                "SELECT id,conversation_id,tool,args_json,reason,status,created_at,resolved_at,resolved_by FROM pending_actions WHERE id=?",
                (pending_id,),
            ).fetchone()
        if not row:
            return None
        try:
            args = json.loads(row[3] or "{}")
        except json.JSONDecodeError:
            args = {}
        return dict(
            id=row[0], conversation_id=row[1], tool=row[2], args=args, reason=row[4],
            status=row[5], created_at=row[6], resolved_at=row[7], resolved_by=row[8],
        )

    def resolve_pending(self, pending_id: str, status: str, resolved_by: str) -> dict | None:
        item = self.get_pending(pending_id)
        if not item or item["status"] != "waiting_for_approval":
            return None
        with self._lock:
            self.db.execute(
                "UPDATE pending_actions SET status=?, resolved_at=?, resolved_by=? WHERE id=?",
                (status, _now(), resolved_by, pending_id),
            )
            self.db.commit()
        item["status"] = status
        item["resolved_by"] = resolved_by
        return item

    # -- durable semantic / owner memory via MemoryStore ---------------
    def remember(self, kind: str, content: str, source: str = "command_chat", confidence: float = 0.8) -> int:
        kind = (kind or "approved_knowledge").strip()
        if kind not in APPROVED_KINDS and kind not in {"fact", "lesson"}:
            kind = "approved_knowledge"
        # Deduplicate exact same content+kind recently
        existing = self.memory.search(content[:80], limit=5)
        for row in existing:
            if row.get("kind") == kind and row.get("content") == content:
                return int(row["id"])
        return int(self.memory.add(kind, content, source, confidence))

    def relevant(self, query: str, limit: int = 8) -> list[dict]:
        hits = self.memory.search(query, limit=limit)
        # Prefer preference/decision/correction/approved_knowledge
        priority = {"preference": 0, "correction": 1, "decision": 2, "approved_knowledge": 3, "feedback": 4, "lesson": 5}
        hits.sort(key=lambda r: (priority.get(r.get("kind"), 9), -(r.get("score") or 0), -int(r.get("id") or 0)))
        return hits[:limit]

    def forget(self, memory_id: int) -> bool:
        return self.memory.forget(memory_id)

    def correct(self, memory_id: int, new_content: str, confidence: float = 0.9) -> bool:
        ok = self.memory.update(memory_id, new_content, confidence=confidence)
        if ok:
            # Keep an explicit correction trail as well
            self.remember("correction", f"Corrected memory #{memory_id}: {new_content}", source="owner_correction", confidence=confidence)
        return ok

    def context_block(self, query: str, limit: int = 6) -> str:
        rows = self.relevant(query, limit=limit)
        if not rows:
            return "(no durable memory hits)"
        lines = []
        for r in rows:
            lines.append(f"- [{r.get('kind')}|id={r.get('id')}] {r.get('content')}")
        return "\n".join(lines)

    def close(self):
        self.db.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
