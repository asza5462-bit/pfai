"""Real username/password auth with HttpOnly sessions (SQLite)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path

from goldbot.config import settings

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_\.]{3,32}$")
SESSION_COOKIE = "aurum_session"
SESSION_TTL = int(os.getenv("AURUM_SESSION_TTL", "604800"))  # 7 days


class AuthError(Exception):
    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code


class UserAuth:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (settings.data_dir / "users.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._secret = (os.getenv("AURUM_AUTH_SECRET") or os.getenv("AURUM_OWNER_TOKEN") or "aurum-dev-secret").encode()
        self._init()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def _init(self) -> None:
        with self._conn() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT NOT NULL UNIQUE,
                  pass_salt TEXT NOT NULL,
                  pass_hash TEXT NOT NULL,
                  created_at REAL NOT NULL,
                  role TEXT NOT NULL DEFAULT 'trader',
                  settings TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS sessions (
                  token TEXT PRIMARY KEY,
                  user_id INTEGER NOT NULL,
                  created_at REAL NOT NULL,
                  expires_at REAL NOT NULL,
                  FOREIGN KEY(user_id) REFERENCES users(id)
                );
                """
            )

    def user_count(self) -> int:
        with self._conn() as c:
            row = c.execute("SELECT COUNT(*) AS n FROM users").fetchone()
        return int(row["n"] if row else 0)

    def needs_setup(self) -> bool:
        return self.user_count() == 0

    @staticmethod
    def _validate_username(username: str) -> str:
        u = (username or "").strip()
        if not USERNAME_RE.match(u):
            raise AuthError("اسم المستخدم يجب أن يكون 3–32 حرفاً (إنجليزي/أرقام/_/.)")
        return u.lower()

    @staticmethod
    def _validate_password(password: str) -> None:
        if not password or len(password) < 8:
            raise AuthError("كلمة المرور 8 أحرف على الأقل")
        if len(password) > 128:
            raise AuthError("كلمة المرور طويلة جداً")

    def _hash(self, password: str, salt: bytes | None = None) -> tuple[str, str]:
        salt = salt or secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
        return base64.b64encode(salt).decode(), base64.b64encode(digest).decode()

    def _verify(self, password: str, salt_b64: str, hash_b64: str) -> bool:
        salt = base64.b64decode(salt_b64.encode())
        _, h = self._hash(password, salt)
        return hmac.compare_digest(h, hash_b64)

    def register(self, username: str, password: str, password_confirm: str) -> dict:
        # First account is always allowed. Later accounts allowed unless locked.
        allow_open = os.getenv("AURUM_OPEN_REGISTER", "1") == "1"
        if self.user_count() > 0 and not allow_open:
            raise AuthError("التسجيل مغلق — تواصل مع المالك", 403)
        if password != password_confirm:
            raise AuthError("تأكيد كلمة المرور غير متطابق")
        u = self._validate_username(username)
        self._validate_password(password)
        salt, digest = self._hash(password)
        role = "owner" if self.user_count() == 0 else "trader"
        try:
            with self._conn() as c:
                cur = c.execute(
                    "INSERT INTO users(username, pass_salt, pass_hash, created_at, role, settings) VALUES (?,?,?,?,?,?)",
                    (u, salt, digest, time.time(), role, "{}"),
                )
                uid = int(cur.lastrowid)
        except sqlite3.IntegrityError:
            raise AuthError("اسم المستخدم مستخدم مسبقاً", 409)
        token = self.create_session(uid)
        return {"user": self.public_user(uid), "token": token, "session_ttl": SESSION_TTL}

    def login(self, username: str, password: str) -> dict:
        u = self._validate_username(username)
        with self._conn() as c:
            row = c.execute("SELECT * FROM users WHERE username=?", (u,)).fetchone()
        if not row or not self._verify(password, row["pass_salt"], row["pass_hash"]):
            raise AuthError("بيانات الدخول غير صحيحة", 401)
        token = self.create_session(int(row["id"]))
        return {"user": self.public_user(int(row["id"])), "token": token, "session_ttl": SESSION_TTL}

    def create_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._conn() as c:
            c.execute(
                "INSERT INTO sessions(token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
                (token, user_id, now, now + SESSION_TTL),
            )
            # prune expired
            c.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        return token

    def logout(self, token: str | None) -> None:
        if not token:
            return
        with self._conn() as c:
            c.execute("DELETE FROM sessions WHERE token=?", (token,))

    def user_from_token(self, token: str | None) -> dict | None:
        if not token:
            return None
        now = time.time()
        with self._conn() as c:
            row = c.execute(
                """SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id
                   WHERE s.token=? AND s.expires_at >= ?""",
                (token, now),
            ).fetchone()
        if not row:
            return None
        return self.public_user(int(row["id"]))

    def public_user(self, user_id: int) -> dict:
        with self._conn() as c:
            row = c.execute("SELECT id, username, role, created_at, settings FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            raise AuthError("المستخدم غير موجود", 404)
        settings_obj = json.loads(row["settings"] or "{}")
        # never expose secrets
        safe_settings = {
            "mt5_login": settings_obj.get("mt5_login") or "",
            "mt5_server": settings_obj.get("mt5_server") or "",
            "mt5_path": settings_obj.get("mt5_path") or "",
            "has_mt5_password": bool(settings_obj.get("mt5_password_enc")),
            "symbol": settings_obj.get("symbol") or settings.symbol,
            "mode": settings_obj.get("mode") or settings.mode,
            "metaapi_account_id": settings_obj.get("metaapi_account_id") or "",
            "metaapi_region": settings_obj.get("metaapi_region") or "",
            "execution": settings_obj.get("execution") or "",
        }
        return {
            "id": int(row["id"]),
            "username": row["username"],
            "role": row["role"],
            "created_at": row["created_at"],
            "settings": safe_settings,
        }

    def _fernet_key(self) -> bytes:
        # Derive 32-byte key
        return hashlib.sha256(self._secret).digest()

    def _encrypt(self, text: str) -> str:
        # Simple XOR+hmac envelope (no extra deps). Fine for local encrypted-at-rest settings.
        key = self._fernet_key()
        raw = text.encode("utf-8")
        out = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
        mac = hmac.new(key, out, hashlib.sha256).digest()
        return base64.b64encode(mac + out).decode()

    def _decrypt(self, blob: str) -> str:
        key = self._fernet_key()
        data = base64.b64decode(blob.encode())
        mac, out = data[:32], data[32:]
        if not hmac.compare_digest(mac, hmac.new(key, out, hashlib.sha256).digest()):
            raise AuthError("تعذّر قراءة الإعدادات المشفّرة", 500)
        raw = bytes(b ^ key[i % len(key)] for i, b in enumerate(out))
        return raw.decode("utf-8")

    def update_settings(self, user_id: int, patch: dict) -> dict:
        with self._conn() as c:
            row = c.execute("SELECT settings FROM users WHERE id=?", (user_id,)).fetchone()
            if not row:
                raise AuthError("المستخدم غير موجود", 404)
            cur = json.loads(row["settings"] or "{}")
            if "mt5_login" in patch:
                cur["mt5_login"] = str(patch.get("mt5_login") or "").strip()
            if "mt5_server" in patch:
                cur["mt5_server"] = str(patch.get("mt5_server") or "").strip()
            if "mt5_path" in patch:
                cur["mt5_path"] = str(patch.get("mt5_path") or "").strip()
            if "mt5_password" in patch and patch.get("mt5_password"):
                cur["mt5_password_enc"] = self._encrypt(str(patch["mt5_password"]))
            if "symbol" in patch and patch.get("symbol"):
                from goldbot.mt5.symbols import normalize_symbol

                cur["symbol"] = normalize_symbol(str(patch["symbol"]))
            if "mode" in patch and patch.get("mode") in {"paper", "mt5"}:
                cur["mode"] = patch["mode"]
            if "metaapi_account_id" in patch:
                from goldbot.mt5.metaapi_cloud import is_metaapi_account_id, normalize_account_id

                raw_id = str(patch.get("metaapi_account_id") or "").strip()
                # Never persist bare numbers like 1215 — MetaApi only accepts UUIDs
                cur["metaapi_account_id"] = normalize_account_id(raw_id) if is_metaapi_account_id(raw_id) else ""
            if "metaapi_region" in patch:
                cur["metaapi_region"] = str(patch.get("metaapi_region") or "").strip()
            if "execution" in patch:
                cur["execution"] = str(patch.get("execution") or "").strip()
            c.execute("UPDATE users SET settings=? WHERE id=?", (json.dumps(cur), user_id))
        return self.public_user(user_id)

    def mt5_secrets(self, user_id: int) -> dict:
        with self._conn() as c:
            row = c.execute("SELECT settings FROM users WHERE id=?", (user_id,)).fetchone()
        cur = json.loads((row["settings"] if row else "{}") or "{}")
        pwd = ""
        if cur.get("mt5_password_enc"):
            try:
                pwd = self._decrypt(cur["mt5_password_enc"])
            except Exception:
                pwd = ""
        return {
            "login": int(cur["mt5_login"]) if str(cur.get("mt5_login") or "").isdigit() else 0,
            "password": pwd,
            "server": cur.get("mt5_server") or "",
            "path": cur.get("mt5_path") or "",
            "mode": cur.get("mode") or "paper",
            "symbol": cur.get("symbol") or settings.symbol,
            "metaapi_account_id": cur.get("metaapi_account_id") or "",
            "metaapi_region": cur.get("metaapi_region") or settings.metaapi_region,
            "execution": cur.get("execution") or "",
        }

    def find_by_mt5_login(self, mt5_login: str) -> int | None:
        login = str(mt5_login or "").strip()
        with self._conn() as c:
            rows = c.execute("SELECT id, settings FROM users").fetchall()
        for row in rows:
            cur = json.loads(row["settings"] or "{}")
            if str(cur.get("mt5_login") or "").strip() == login:
                return int(row["id"])
        return None

    def login_with_mt5(self, mt5_login: str, mt5_password: str, mt5_server: str, symbol: str = "XAUUSDm") -> dict:
        """Primary Exness/MT5 login — creates account bound to trading number if needed."""
        from goldbot.mt5.symbols import normalize_symbol

        login = str(mt5_login or "").strip()
        if not login.isdigit() or len(login) < 5:
            raise AuthError("رقم حساب MT5/Exness غير صالح")
        if not mt5_password or len(mt5_password) < 4:
            raise AuthError("كلمة مرور MT5 مطلوبة")
        server = (mt5_server or "").strip()
        if not server:
            raise AuthError("اختر سيرفر Exness (مثل Exness-MT5Trial)")

        uid = self.find_by_mt5_login(login)
        if uid is None:
            # auto provision app user from MT5 login
            username = f"exness_{login}"
            # ensure unique
            base = username
            n = 1
            while True:
                try:
                    self._validate_username(username if n == 1 else f"{base}_{n}")
                    # create with random app password (user logs in via MT5 form)
                    app_pass = secrets.token_urlsafe(16)
                    salt, digest = self._hash(app_pass)
                    role = "owner" if self.user_count() == 0 else "trader"
                    uname = username if n == 1 else f"{base}_{n}"
                    with self._conn() as c:
                        cur = c.execute(
                            "INSERT INTO users(username, pass_salt, pass_hash, created_at, role, settings) VALUES (?,?,?,?,?,?)",
                            (uname, salt, digest, time.time(), role, "{}"),
                        )
                        uid = int(cur.lastrowid)
                    break
                except (AuthError, sqlite3.IntegrityError):
                    n += 1
                    if n > 20:
                        raise AuthError("تعذّر إنشاء حساب مرتبط")
        assert uid is not None
        self.update_settings(
            uid,
            {
                "mt5_login": login,
                "mt5_password": mt5_password,
                "mt5_server": server,
                "symbol": normalize_symbol(symbol or "XAUUSDm"),
                "mode": "mt5",
            },
        )
        session = self.create_session(uid)
        return {"user": self.public_user(uid), "token": session, "session_ttl": SESSION_TTL}


auth = UserAuth()
