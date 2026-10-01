"""SQLite persistence with encrypted provider secrets."""
from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


class Database:
    def __init__(self) -> None:
        self.path = settings.database_path
        self._write_lock = threading.RLock()
        key_material = settings.app_secret or "nova-development-only-secret"
        key = base64.urlsafe_b64encode(hashlib.sha256(key_material.encode()).digest())
        self._cipher = Fernet(key)
        self.init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock:
            conn = self.connect()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def init(self) -> None:
        with self.transaction() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'owner',
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    expires_at REAL NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS file_revisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    content TEXT,
                    checksum TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS settings (
                    user_id INTEGER NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    encrypted INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(user_id, key),
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    action TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, id);
                CREATE INDEX IF NOT EXISTS idx_file_revisions
                    ON file_revisions(project_id, path, id DESC);
                """
            )

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        with self.transaction() as conn:
            cur = conn.execute(sql, params)
            return int(cur.lastrowid or 0)

    def audit(self, user_id: int | None, action: str, detail: dict[str, Any] | None = None) -> None:
        self.execute(
            "INSERT INTO audit_log(user_id, action, detail, created_at) VALUES (?,?,?,?)",
            (user_id, action, json.dumps(detail or {}, ensure_ascii=False), time.time()),
        )

    def set_setting(self, user_id: int, key: str, value: str, *, encrypted: bool = False) -> None:
        stored = self._cipher.encrypt(value.encode()).decode() if encrypted and value else value
        self.execute(
            """
            INSERT INTO settings(user_id, key, value, encrypted, updated_at)
            VALUES (?,?,?,?,?)
            ON CONFLICT(user_id, key) DO UPDATE SET
              value=excluded.value, encrypted=excluded.encrypted, updated_at=excluded.updated_at
            """,
            (user_id, key, stored, int(encrypted), time.time()),
        )

    def get_setting(self, user_id: int, key: str, default: str = "") -> str:
        row = self.one("SELECT value, encrypted FROM settings WHERE user_id=? AND key=?", (user_id, key))
        if not row:
            return default
        value = str(row["value"])
        if row["encrypted"] and value:
            try:
                return self._cipher.decrypt(value.encode()).decode()
            except InvalidToken:
                return ""
        return value


db = Database()
