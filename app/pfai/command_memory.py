"""Command Chat memory — legendary, conflict-safe, owner-scoped.

Learning here means durable memory / feedback / approved knowledge —
never automatic model-weight mutation.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .memory import MemoryStore
from . import memory_guardian as guardian

log = logging.getLogger("pfai.command_memory")

APPROVED_KINDS = {
    "preference",
    "decision",
    "approved_knowledge",
    "correction",
    "feedback",
    "conversation_note",
    "fact",
    "lesson",
    "epic_memory",
    "user_desire",
    "identity",
}


class CommandMemoryService:
    VERSION = "8.13.0"

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
                CREATE TABLE IF NOT EXISTS legendary_facts (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  subject TEXT,
                  predicate TEXT,
                  object TEXT,
                  confidence REAL,
                  source TEXT,
                  created_at TEXT,
                  last_seen TEXT
                );
                CREATE TABLE IF NOT EXISTS conversation_digests (
                  conversation_id TEXT PRIMARY KEY,
                  digest TEXT,
                  turn_count INTEGER,
                  updated_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_legendary_subject ON legendary_facts(subject);
                """
            )
            self._migrate_schema()
            self.db.commit()

    def _migrate_schema(self) -> None:
        """Additive columns for owner scope + conflict status."""
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(legendary_facts)").fetchall()}
        alters = []
        if "owner" not in cols:
            alters.append("ALTER TABLE legendary_facts ADD COLUMN owner TEXT DEFAULT ''")
        if "status" not in cols:
            alters.append("ALTER TABLE legendary_facts ADD COLUMN status TEXT DEFAULT 'active'")
        if "scope" not in cols:
            alters.append("ALTER TABLE legendary_facts ADD COLUMN scope TEXT DEFAULT 'user'")
        if "conversation_id" not in cols:
            alters.append("ALTER TABLE legendary_facts ADD COLUMN conversation_id TEXT DEFAULT ''")
        for sql in alters:
            try:
                self.db.execute(sql)
            except sqlite3.OperationalError as exc:
                log.debug("migrate skip: %s", exc)
        # conversations owner
        ccols = {r[1] for r in self.db.execute("PRAGMA table_info(conversations)").fetchall()}
        if "owner" not in ccols:
            try:
                self.db.execute("ALTER TABLE conversations ADD COLUMN owner TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_legendary_owner_pred ON legendary_facts(owner, predicate, status)"
        )

    # -- conversations -------------------------------------------------
    def create_conversation(self, title: str = "PFAI Command Chat", owner: str = "") -> str:
        cid = uuid.uuid4().hex
        now = _now()
        with self._lock:
            try:
                self.db.execute(
                    "INSERT INTO conversations(id,title,created_at,updated_at,owner) VALUES(?,?,?,?,?)",
                    (cid, title, now, now, owner or ""),
                )
            except sqlite3.OperationalError:
                self.db.execute(
                    "INSERT INTO conversations(id,title,created_at,updated_at) VALUES(?,?,?,?)",
                    (cid, title, now, now),
                )
            self.db.commit()
        return cid

    def list_conversations(self, limit: int = 30, owner: str = "") -> list[dict]:
        with self._lock:
            if owner:
                try:
                    rows = self.db.execute(
                        "SELECT id,title,created_at,updated_at FROM conversations "
                        "WHERE owner=? OR owner='' OR owner IS NULL "
                        "ORDER BY updated_at DESC LIMIT ?",
                        (owner, int(limit)),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = self.db.execute(
                        "SELECT id,title,created_at,updated_at FROM conversations ORDER BY updated_at DESC LIMIT ?",
                        (int(limit),),
                    ).fetchall()
            else:
                rows = self.db.execute(
                    "SELECT id,title,created_at,updated_at FROM conversations ORDER BY updated_at DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
        return [dict(id=r[0], title=r[1], created_at=r[2], updated_at=r[3]) for r in rows]

    def ensure_conversation(self, conversation_id: str | None, owner: str = "") -> str:
        if conversation_id:
            with self._lock:
                row = self.db.execute("SELECT id FROM conversations WHERE id=?", (conversation_id,)).fetchone()
            if row:
                if owner:
                    try:
                        with self._lock:
                            self.db.execute(
                                "UPDATE conversations SET owner=? WHERE id=? AND (owner='' OR owner IS NULL)",
                                (owner, conversation_id),
                            )
                            self.db.commit()
                    except sqlite3.OperationalError:
                        pass
                return conversation_id
        return self.create_conversation(owner=owner)

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
        content, redacted = guardian.redact_secrets(content or "")
        if redacted:
            source = f"{source}|redacted"
        if not content.strip():
            return 0
        # Deduplicate exact same content+kind
        existing = self.memory.search(content[:80], limit=8)
        for row in existing:
            if row.get("kind") == kind and row.get("content") == content:
                return int(row["id"])
        # Supersede conflicting identity/preference content for same kind key prefix
        if kind in {"identity", "preference", "user_desire"}:
            self._supersede_similar_durable(kind, content)
        return int(self.memory.add(kind, content, source, confidence))

    def _supersede_similar_durable(self, kind: str, content: str) -> int:
        """Forget older rows of same kind that clearly conflict (e.g. name lines)."""
        removed = 0
        # Identity: keep only newest "name=" style
        if kind == "identity" or re.search(r"(?i)اسم|name\s*is|اسمي", content):
            for row in self.memory.list_by_kind("identity", limit=40) + self.memory.list_by_kind("epic_memory", limit=40):
                c = row.get("content") or ""
                if row.get("content") == content:
                    continue
                if re.search(r"(?i)اسمي|my name is|name_is|اسم المستخدم", c) and re.search(r"(?i)اسمي|my name is|name_is|اسم المستخدم", content):
                    if self.memory.forget(int(row["id"])):
                        removed += 1
        return removed

    def relevant(self, query: str, limit: int = 8, *, include_coding: bool | None = None) -> list[dict]:
        tokens = [t for t in re_split_tokens(query) if len(t) >= 3][:8]
        hits = list(self.memory.search(query, limit=max(limit, 12)) or [])
        seen = {h.get("id") for h in hits}
        for tok in tokens:
            for h in self.memory.search(tok, limit=4) or []:
                if h.get("id") in seen:
                    continue
                seen.add(h.get("id"))
                hits.append(h)
        if include_coding is None:
            include_coding = guardian.is_coding_query(query)
        if not include_coding:
            hits = guardian.filter_durable_for_context(hits, query)
        priority = {
            "identity": 0, "preference": 0, "user_desire": 0, "correction": 1, "decision": 2,
            "epic_memory": 2, "approved_knowledge": 3, "fact": 3, "feedback": 4, "lesson": 5,
        }
        hits.sort(key=lambda r: (
            priority.get(r.get("kind"), 9),
            -(float(r.get("score") or r.get("confidence") or 0)),
            -int(r.get("id") or 0),
        ))
        return hits[:limit]

    def forget(self, memory_id: int) -> bool:
        return self.memory.forget(memory_id)

    def correct(self, memory_id: int, new_content: str, confidence: float = 0.9) -> bool:
        new_content, _ = guardian.redact_secrets(new_content or "")
        ok = self.memory.update(memory_id, new_content, confidence=confidence)
        if ok:
            self.remember("correction", f"Corrected memory #{memory_id}: {new_content}", source="owner_correction", confidence=confidence)
        return ok

    def context_block(self, query: str, limit: int = 6) -> str:
        return self.legendary_context(query, limit=limit)

    # -- legendary memory ----------------------------------------------
    def remember_fact(
        self,
        subject: str,
        predicate: str,
        obj: str,
        *,
        confidence: float = 0.85,
        source: str = "chat",
        owner: str = "",
        conversation_id: str = "",
        scope: str = "user",
    ) -> int:
        subject = (subject or "").strip()[:120]
        predicate = (predicate or "").strip()[:80]
        obj, redacted = guardian.redact_secrets((obj or "").strip()[:400])
        if redacted:
            source = f"{source}|redacted"
        if not subject or not obj or not predicate:
            return 0
        now = _now()
        with self._lock:
            # Exact active match → refresh
            row = self.db.execute(
                "SELECT id FROM legendary_facts WHERE subject=? AND predicate=? AND object=? "
                "AND COALESCE(status,'active')='active' AND COALESCE(owner,'')=? LIMIT 1",
                (subject, predicate, obj, owner or ""),
            ).fetchone()
            if row:
                self.db.execute(
                    "UPDATE legendary_facts SET last_seen=?, confidence=? WHERE id=?",
                    (now, float(confidence), row[0]),
                )
                self.db.commit()
                return int(row[0])

            # Conflict: same subject+predicate, different object → supersede losers
            rivals = self.db.execute(
                "SELECT id, object, confidence, last_seen FROM legendary_facts "
                "WHERE subject=? AND predicate=? AND COALESCE(status,'active')='active' "
                "AND COALESCE(owner,'')=?",
                (subject, predicate, owner or ""),
            ).fetchall()
            for r in rivals:
                if str(r[1]) != obj:
                    self.db.execute(
                        "UPDATE legendary_facts SET status='superseded', last_seen=? WHERE id=?",
                        (now, r[0]),
                    )
                    log.info(
                        "memory conflict supersede id=%s %s.%s '%s' → '%s' owner=%s",
                        r[0], subject, predicate, r[1], obj, owner or "*",
                    )

            cur = self.db.execute(
                "INSERT INTO legendary_facts(subject,predicate,object,confidence,source,created_at,last_seen,owner,status,scope,conversation_id) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (subject, predicate, obj, float(confidence), source, now, now, owner or "", "active", scope, conversation_id or ""),
            )
            self.db.commit()
            return int(cur.lastrowid)

    def recall_facts(self, query: str, limit: int = 8, *, owner: str = "") -> list[dict]:
        tokens = [t for t in re_split_tokens(query) if len(t) >= 2][:10]
        # Always include identity tokens for name questions
        if re.search(r"(?i)اسم|name|أنا|who\s+am", query or ""):
            tokens = list(dict.fromkeys(["name", "اسم", "user"] + tokens))
        if not tokens:
            tokens = ["user"]
        out: list[dict] = []
        seen = set()
        with self._lock:
            for tok in tokens:
                if owner:
                    rows = self.db.execute(
                        "SELECT id,subject,predicate,object,confidence,source,last_seen,COALESCE(status,'active'),COALESCE(owner,'') "
                        "FROM legendary_facts "
                        "WHERE COALESCE(status,'active')='active' "
                        "AND (COALESCE(owner,'')=? OR COALESCE(owner,'')='') "
                        "AND (subject LIKE ? OR object LIKE ? OR predicate LIKE ?) "
                        "ORDER BY last_seen DESC LIMIT ?",
                        (owner, f"%{tok}%", f"%{tok}%", f"%{tok}%", max(3, limit)),
                    ).fetchall()
                else:
                    rows = self.db.execute(
                        "SELECT id,subject,predicate,object,confidence,source,last_seen,COALESCE(status,'active'),COALESCE(owner,'') "
                        "FROM legendary_facts "
                        "WHERE COALESCE(status,'active')='active' "
                        "AND (subject LIKE ? OR object LIKE ? OR predicate LIKE ?) "
                        "ORDER BY last_seen DESC LIMIT ?",
                        (f"%{tok}%", f"%{tok}%", f"%{tok}%", max(3, limit)),
                    ).fetchall()
                for r in rows:
                    if r[0] in seen:
                        continue
                    seen.add(r[0])
                    out.append(dict(
                        id=r[0], subject=r[1], predicate=r[2], object=r[3],
                        confidence=r[4], source=r[5], last_seen=r[6],
                        status=r[7], owner=r[8],
                    ))
        # Collapse remaining conflicts by winner
        by_key: dict[tuple[str, str], list[dict]] = {}
        for f in out:
            by_key.setdefault((f["subject"], f["predicate"]), []).append(f)
        collapsed = []
        for rows in by_key.values():
            w = guardian.pick_winner_fact(rows)
            if w:
                collapsed.append(w)
        collapsed.sort(key=lambda f: (float(f.get("confidence") or 0), str(f.get("last_seen") or "")), reverse=True)
        return collapsed[:limit]

    def list_active_facts(self, *, owner: str = "", limit: int = 200) -> list[dict]:
        with self._lock:
            if owner:
                rows = self.db.execute(
                    "SELECT id,subject,predicate,object,confidence,source,last_seen,COALESCE(status,'active'),COALESCE(owner,'') "
                    "FROM legendary_facts WHERE COALESCE(status,'active')='active' "
                    "AND (COALESCE(owner,'')=? OR COALESCE(owner,'')='') "
                    "ORDER BY last_seen DESC LIMIT ?",
                    (owner, int(limit)),
                ).fetchall()
            else:
                rows = self.db.execute(
                    "SELECT id,subject,predicate,object,confidence,source,last_seen,COALESCE(status,'active'),COALESCE(owner,'') "
                    "FROM legendary_facts WHERE COALESCE(status,'active')='active' "
                    "ORDER BY last_seen DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
        return [
            dict(id=r[0], subject=r[1], predicate=r[2], object=r[3], confidence=r[4],
                 source=r[5], last_seen=r[6], status=r[7], owner=r[8])
            for r in rows
        ]

    def update_digest(self, conversation_id: str, dialog: list[dict]) -> str:
        """Compress recent dialog into a durable conversation digest (no template spam)."""
        if not conversation_id or not dialog:
            return ""
        digest = guardian.digest_from_dialog(dialog)
        with self._lock:
            self.db.execute(
                "INSERT INTO conversation_digests(conversation_id,digest,turn_count,updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(conversation_id) DO UPDATE SET digest=excluded.digest, turn_count=excluded.turn_count, updated_at=excluded.updated_at",
                (conversation_id, digest, len(dialog), _now()),
            )
            self.db.commit()
        return digest

    def get_digest(self, conversation_id: str) -> str:
        if not conversation_id:
            return ""
        with self._lock:
            row = self.db.execute(
                "SELECT digest FROM conversation_digests WHERE conversation_id=?",
                (conversation_id,),
            ).fetchone()
        return (row[0] if row else "") or ""

    def ingest_user_turn(
        self,
        message: str,
        *,
        conversation_id: str = "",
        owner: str = "",
    ) -> dict:
        """Auto-capture identity/desires/preferences/facts (legendary intake)."""
        text = (message or "").strip()
        stored = []
        if not text:
            return {"stored": 0, "redacted": False}
        text, redacted = guardian.redact_secrets(text)

        # Structured identity + language prefs
        for fact in guardian.extract_identity_and_prefs(text):
            mid = self.remember_fact(
                fact["subject"], fact["predicate"], fact["object"],
                confidence=float(fact.get("confidence") or 0.9),
                source="legendary_ingest",
                owner=owner,
                conversation_id=conversation_id,
            )
            kind = fact.get("kind") or "fact"
            did = self.remember(
                kind if kind in APPROVED_KINDS else "identity",
                f"{fact['predicate']}={fact['object']}",
                source="legendary_ingest",
                confidence=float(fact.get("confidence") or 0.9),
            )
            stored.append((kind, mid or did))

        # Desires
        m = re.search(r"(?:أريد|اريد|I want|I need)\s+(.{8,240})", text, re.I)
        if m:
            desire = m.group(1).strip()
            mid = self.remember("user_desire", desire, source="legendary_ingest", confidence=0.9)
            self.remember_fact("user", "desires", desire, confidence=0.9, source="legendary_ingest", owner=owner, conversation_id=conversation_id)
            stored.append(("user_desire", mid))

        # Preferences
        m = re.search(r"(?:فضّل|prefer|دائماً|always|لا ت(?:قم|فعل)|never)\s+(.{6,200})", text, re.I)
        if m:
            pref = m.group(1).strip()
            mid = self.remember("preference", pref, source="legendary_ingest", confidence=0.85)
            self.remember_fact("user", "prefers", pref, confidence=0.85, source="legendary_ingest", owner=owner, conversation_id=conversation_id)
            stored.append(("preference", mid))

        # Explicit remember requests
        if re.search(r"\bremember\b|تذكّر|تذكر هذا|احفظ|تذكر أن", text, re.I):
            mid = self.remember("epic_memory", text[:500], source="legendary_ingest", confidence=0.95)
            stored.append(("epic_memory", mid))

        if conversation_id:
            self.update_digest(conversation_id, self.recent_dialog(conversation_id, limit=16))
        return {"stored": len(stored), "items": stored, "redacted": redacted, "version": self.VERSION}

    def legendary_context(
        self,
        query: str,
        *,
        conversation_id: str = "",
        owner: str = "",
        limit: int = 10,
    ) -> str:
        """Rich memory block: durable hits + conflict-free facts + clean digest."""
        rows = self.relevant(query, limit=limit)
        facts = self.recall_facts(query, limit=8, owner=owner)
        digest = self.get_digest(conversation_id) if conversation_id else ""
        lines = ["## Legendary Memory", f"version={self.VERSION}"]
        if owner:
            lines.append(f"owner_scope: {owner}")
        if digest:
            lines.append(f"Thread digest: {digest[:500]}")
        if facts:
            lines.append("Facts (active, conflict-resolved):")
            for f in facts:
                lines.append(f"- ({f.get('subject')}) {f.get('predicate')} → {f.get('object')}")
        if rows:
            lines.append("Durable:")
            for r in rows:
                lines.append(f"- [{r.get('kind')}|id={r.get('id')}|c={r.get('confidence')}] {r.get('content')}")
        direct = guardian.answer_from_facts(facts, query, language="ar" if re.search(r"[\u0600-\u06FF]", query or "") else "en")
        if direct:
            lines.append(f"DirectAnswer: {direct}")
        if len(lines) <= 2:
            return "(no durable memory hits)"
        return "\n".join(lines)

    def direct_answer(self, query: str, *, owner: str = "", language: str = "ar") -> str | None:
        facts = self.recall_facts(query, limit=12, owner=owner)
        return guardian.answer_from_facts(facts, query, language=language)

    def heal_conflicts(self, *, owner: str = "") -> dict[str, Any]:
        """Resolve all subject+predicate conflicts by superseding losers."""
        facts = self.list_active_facts(owner=owner, limit=500)
        conflicts = guardian.find_fact_conflicts(facts)
        superseded = 0
        now = _now()
        with self._lock:
            for c in conflicts:
                rows = [f for f in facts if f.get("subject") == c["subject"] and f.get("predicate") == c["predicate"]]
                winner = guardian.pick_winner_fact(rows)
                if not winner:
                    continue
                for r in rows:
                    if r.get("id") == winner.get("id"):
                        continue
                    self.db.execute(
                        "UPDATE legendary_facts SET status='superseded', last_seen=? WHERE id=?",
                        (now, int(r["id"])),
                    )
                    superseded += 1
            self.db.commit()
        report = self.audit(owner=owner)
        return {"ok": True, "superseded": superseded, "conflicts_before": len(conflicts), "audit": report}

    def audit(self, *, owner: str = "") -> dict[str, Any]:
        facts = self.list_active_facts(owner=owner, limit=500)
        durable = list(self.memory.all_documents() or [])[:500]
        if not guardian.is_coding_query("audit"):
            # full durable list for secret/coding bleed detection
            pass
        report = guardian.integrity_report(facts=facts, durable=durable, owner=owner)
        report["version"] = self.VERSION
        return report

    def close(self):
        self.db.close()


def re_split_tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^\w\u0600-\u06FF]+", (text or "").lower()) if t]


def re_sub_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
