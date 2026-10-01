"""Single-owner authentication with hardened cookie sessions."""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass

from fastapi import Cookie, Header, HTTPException, Request, Response

from app.config import settings
from app.database import db

COOKIE_NAME = "nova_session"
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


@dataclass(slots=True)
class AuthResult:
    user: dict
    token: str


def _password_hash(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return base64.b64encode(salt).decode(), base64.b64encode(digest).decode()


def _public_user(row: dict) -> dict:
    return {"id": int(row["id"]), "username": row["username"], "role": row["role"]}


def user_count() -> int:
    row = db.one("SELECT COUNT(*) AS n FROM users")
    return int(row["n"]) if row else 0


def setup_owner(username: str, password: str, setup_token: str) -> AuthResult:
    if user_count() > 0:
        raise HTTPException(409, "تم إعداد المالك مسبقاً")
    if settings.setup_token and not hmac.compare_digest(setup_token, settings.setup_token):
        raise HTTPException(403, "رمز الإعداد غير صحيح")
    if not settings.setup_token and settings.production_ready:
        raise HTTPException(503, "رمز الإعداد غير مكوّن")
    if not USERNAME_RE.fullmatch(username.strip()):
        raise HTTPException(400, "اسم المستخدم 3–32 حرفاً إنجليزياً أو رقماً")
    if len(password) < 12:
        raise HTTPException(400, "كلمة المرور يجب أن تكون 12 حرفاً على الأقل")
    salt, digest = _password_hash(password)
    now = time.time()
    user_id = db.execute(
        "INSERT INTO users(username, password_hash, password_salt, role, created_at) VALUES (?,?,?,?,?)",
        (username.strip().lower(), digest, salt, "owner", now),
    )
    db.audit(user_id, "owner.setup")
    return AuthResult(user={"id": user_id, "username": username.strip().lower(), "role": "owner"}, token=create_session(user_id))


def login(username: str, password: str) -> AuthResult:
    row = db.one("SELECT * FROM users WHERE username=?", (username.strip().lower(),))
    if not row:
        raise HTTPException(401, "بيانات الدخول غير صحيحة")
    salt = base64.b64decode(row["password_salt"])
    _, candidate = _password_hash(password, salt)
    if not hmac.compare_digest(candidate, row["password_hash"]):
        raise HTTPException(401, "بيانات الدخول غير صحيحة")
    token = create_session(int(row["id"]))
    db.audit(int(row["id"]), "auth.login")
    return AuthResult(user=_public_user(row), token=token)


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()
    expires = now + settings.session_days * 86400
    db.execute(
        "INSERT INTO sessions(token_hash, user_id, expires_at, created_at) VALUES (?,?,?,?)",
        (token_hash, user_id, expires, now),
    )
    db.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
    return token


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )


def logout(token: str | None) -> None:
    if token:
        db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))


def token_from(authorization: str | None, cookie: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return cookie


def current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    nova_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> dict:
    token = token_from(authorization, nova_session)
    if not token:
        raise HTTPException(401, "يلزم تسجيل الدخول")
    row = db.one(
        """
        SELECT users.id, users.username, users.role
        FROM sessions JOIN users ON users.id=sessions.user_id
        WHERE sessions.token_hash=? AND sessions.expires_at>?
        """,
        (hashlib.sha256(token.encode()).hexdigest(), time.time()),
    )
    if not row:
        raise HTTPException(401, "انتهت الجلسة")
    request.state.user = row
    return _public_user(row)
