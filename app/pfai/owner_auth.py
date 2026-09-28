"""Owner authentication: setup, sessions, rate-limit, lockout, username+password.

Integrates with OwnerControl — does not replace it.
Never stores or logs plaintext passwords. Never returns hashes to clients
except via operator-side tooling that hashes stdin locally.

Email OTP and email-based login were permanently removed.
Owner auth is username + password (+ HttpOnly session cookie, optional X-Owner-Secret).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from .owner_control import OwnerControl

COOKIE_NAME = "pfai_owner_session"
AUTH_FAIL_MESSAGE = "authentication failed"
SETUP_DISABLED_MESSAGE = "owner setup is disabled"
WEAK_PASS_MESSAGE = "password does not meet strength requirements"

# Tunables (override via env for ops, not secrets)
DEFAULT_SESSION_TTL = int(os.environ.get("PFAI_OWNER_SESSION_TTL", "28800"))  # 8h
DEFAULT_SESSION_ABS_MAX = int(os.environ.get("PFAI_OWNER_SESSION_ABS_MAX", "86400"))  # 24h hard auto-lock
MAX_FAILURES = int(os.environ.get("PFAI_OWNER_MAX_FAILURES", "5"))
LOCKOUT_SECONDS = int(os.environ.get("PFAI_OWNER_LOCKOUT_SECONDS", "900"))
PBKDF2_ITERATIONS = int(os.environ.get("PFAI_OWNER_PBKDF2_ITERATIONS", "260000"))
MIN_PASSCODE_LEN = int(os.environ.get("PFAI_OWNER_MIN_PASSCODE_LEN", "12"))
_USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


def normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def username_valid(username: str) -> bool:
    u = normalize_username(username)
    if not u or "@" in u or " " in u:
        return False
    return bool(_USERNAME_RE.match(u))


class OwnerAuthService:
    def __init__(
        self,
        owner: OwnerControl,
        *,
        root: str = "data/security",
        session_ttl: int = DEFAULT_SESSION_TTL,
        session_abs_max: int = DEFAULT_SESSION_ABS_MAX,
    ) -> None:
        self.owner = owner
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.credentials_path = self.root / "owner_credentials.json"
        self.setup_lock_path = self.root / "owner_setup.lock"
        self.sessions_path = self.root / "owner_sessions.json"
        self.rate_path = self.root / "owner_auth_rate.json"
        self.session_ttl = int(session_ttl)
        self.session_abs_max = int(session_abs_max)
        self._lock = threading.RLock()
        self._hydrate_env_from_store()

    # --- public status -------------------------------------------------
    def public_status(self, *, authenticated: bool = False, username: str = "") -> dict[str, Any]:
        return {
            "setup_required": self.setup_required(),
            "setup_locked": self.setup_locked(),
            "owner_configured": self.owner_configured(),
            "authenticated": bool(authenticated),
            "username": username if authenticated else "",
            "session_ttl_seconds": self.session_ttl,
            "session_abs_max_seconds": self.session_abs_max,
            "auth_methods": [
                "password",
                "session_cookie",
                "x_owner_secret_header",
            ],
            "email_otp": "REMOVED",
            "email_auth": "REMOVED",
            "note": "Passwords are never returned. Configure owner username and secret via deployment environment. Email login/OTP permanently removed.",
        }

    def setup_required(self) -> bool:
        if self.setup_locked():
            return False
        return not self.owner_configured()

    def setup_locked(self) -> bool:
        return self.setup_lock_path.exists()

    def owner_configured(self) -> bool:
        return bool(self.owner.owner_username()) and bool(self._configured_hash())

    # --- hashing -------------------------------------------------------
    @staticmethod
    def hash_passcode(passcode: str, *, salt: bytes | None = None, iterations: int = PBKDF2_ITERATIONS) -> str:
        if not passcode:
            raise ValueError("password required")
        salt = salt or secrets.token_bytes(16)
        dk = hashlib.pbkdf2_hmac("sha256", passcode.encode("utf-8"), salt, int(iterations))
        return f"pbkdf2_sha256${int(iterations)}${salt.hex()}${dk.hex()}"

    @staticmethod
    def verify_passcode(passcode: str, stored: str) -> bool:
        if not passcode or not stored:
            return False
        stored = stored.strip()
        if stored.startswith("pbkdf2_sha256$"):
            try:
                _, iters_s, salt_hex, hash_hex = stored.split("$", 3)
                iterations = int(iters_s)
                salt = bytes.fromhex(salt_hex)
                dk = hashlib.pbkdf2_hmac("sha256", passcode.encode("utf-8"), salt, iterations)
                return hmac.compare_digest(dk.hex(), hash_hex)
            except Exception:
                return False
        # Legacy SHA-256 hex (OwnerControl.hash_secret) — still accepted for existing envs/tests
        legacy = hashlib.sha256(passcode.encode("utf-8")).hexdigest()
        return hmac.compare_digest(legacy, stored)

    @staticmethod
    def passcode_strong(passcode: str) -> bool:
        if len(passcode or "") < MIN_PASSCODE_LEN:
            return False
        classes = sum(
            [
                any(c.islower() for c in passcode),
                any(c.isupper() for c in passcode),
                any(c.isdigit() for c in passcode),
                any(not c.isalnum() for c in passcode),
            ]
        )
        return classes >= 3

    # --- setup (once) --------------------------------------------------
    def run_setup(self, username: str, password: str, password_confirm: str) -> dict[str, Any]:
        username = normalize_username(username)
        if self.setup_locked() or self.owner_configured():
            self.owner._audit("SETUP_BLOCKED", {"reason": "already_initialized"})
            return {"ok": False, "error": SETUP_DISABLED_MESSAGE}

        if not username_valid(username):
            return {"ok": False, "error": "invalid setup request"}
        if password != password_confirm:
            return {"ok": False, "error": "invalid setup request"}
        if not self.passcode_strong(password):
            return {"ok": False, "error": WEAK_PASS_MESSAGE}

        env_user = normalize_username(os.environ.get(self.owner.username_env) or "")
        if env_user and env_user != username:
            self.owner._audit("SETUP_BLOCKED", {"reason": "username_mismatch"})
            return {"ok": False, "error": "invalid setup request"}

        digest = self.hash_passcode(password)
        self._write_credentials(username, digest)
        self._write_setup_lock(username)
        os.environ[self.owner.username_env] = username
        os.environ[self.owner.secret_env] = digest
        self.owner._audit("SETUP_COMPLETED", {"username": username})
        return {
            "ok": True,
            "username": username,
            "setup_locked": True,
            "message": "Owner setup complete. Plaintext password is not stored. "
            "Before production deploy, set a NEW password hash via environment secrets.",
        }

    # --- login / logout / session --------------------------------------
    def login(self, username: str, password: str, *, client_key: str) -> dict[str, Any]:
        username = normalize_username(username)
        client_key = (client_key or "unknown")[:128]
        if self._is_locked(client_key):
            self.owner._audit("AUTH_LOCKOUT", {"client": client_key})
            return {"ok": False, "error": AUTH_FAIL_MESSAGE, "locked": True}

        configured = normalize_username(self.owner.owner_username() or "")
        stored_hash = self._configured_hash()
        ok = bool(
            configured
            and stored_hash
            and username
            and username_valid(username)
            and hmac.compare_digest(username, configured)
            and self.verify_passcode(password, stored_hash)
        )
        if not ok:
            self._register_failure(client_key)
            self.owner._audit(
                "AUTH_FAILURE",
                {"username_attempt_present": bool(username), "client": client_key},
            )
            return {"ok": False, "error": AUTH_FAIL_MESSAGE, "locked": self._is_locked(client_key)}

        self._clear_failures(client_key)
        token = secrets.token_urlsafe(32)
        self._put_session(token, configured)
        self.owner._audit("AUTH_SUCCESS", {"username": configured, "client": client_key})
        return {"ok": True, "username": configured, "token": token, "expires_in": self.session_ttl}

    def logout(self, token: str | None) -> dict[str, Any]:
        if token:
            self._drop_session(token)
            self.owner._audit("LOGOUT", {})
        return {"ok": True}

    def resolve_session(self, token: str | None) -> str | None:
        if not token:
            return None
        with self._lock:
            sessions = self._load_json(self.sessions_path, {})
            key = self._token_key(token)
            rec = sessions.get(key)
            if not rec:
                return None
            now = time.time()
            created = float(rec.get("created_at") or 0)
            if created and (now - created) > self.session_abs_max:
                sessions.pop(key, None)
                self._save_json(self.sessions_path, sessions)
                self.owner._audit("SESSION_ABS_EXPIRED", {"username": rec.get("username") or rec.get("email")})
                return None
            if float(rec.get("expires_at", 0)) < now:
                sessions.pop(key, None)
                self._save_json(self.sessions_path, sessions)
                return None
            remaining_abs = self.session_abs_max - (now - created) if created else self.session_ttl
            rec["expires_at"] = now + min(self.session_ttl, max(1, int(remaining_abs)))
            sessions[key] = rec
            self._save_json(self.sessions_path, sessions)
            return str(rec.get("username") or rec.get("email") or "")

    def authenticate_secret_header(self, presented_secret: str) -> bool:
        """Legacy header auth used by API clients/tests — still server-side only."""
        stored = self._configured_hash()
        if not stored or not presented_secret:
            return False
        return self.verify_passcode(presented_secret, stored)

    # --- internals -----------------------------------------------------
    def _configured_hash(self) -> str:
        env_hash = os.environ.get(self.owner.secret_env, "")
        if env_hash:
            return env_hash
        data = self._load_json(self.credentials_path, {})
        return str(data.get("secret_hash") or "")

    def _hydrate_env_from_store(self) -> None:
        data = self._load_json(self.credentials_path, {})
        username = data.get("username") or data.get("email")
        if username and not os.environ.get(self.owner.username_env):
            os.environ[self.owner.username_env] = normalize_username(str(username))
        if data.get("secret_hash") and not os.environ.get(self.owner.secret_env):
            os.environ[self.owner.secret_env] = str(data["secret_hash"])

    def _write_credentials(self, username: str, digest: str) -> None:
        payload = {
            "username": username,
            "secret_hash": digest,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "algo": "pbkdf2_sha256",
        }
        self._save_json(self.credentials_path, payload)
        try:
            os.chmod(self.credentials_path, 0o600)
        except OSError:
            pass

    def _write_setup_lock(self, username: str) -> None:
        payload = {
            "locked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "username": username,
            "note": "Owner setup permanently disabled. Recovery requires out-of-band env secrets.",
        }
        self.setup_lock_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            os.chmod(self.setup_lock_path, 0o600)
        except OSError:
            pass

    def _token_key(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _put_session(self, token: str, username: str) -> None:
        with self._lock:
            sessions = self._load_json(self.sessions_path, {})
            sessions[self._token_key(token)] = {
                "username": username,
                "created_at": time.time(),
                "expires_at": time.time() + self.session_ttl,
            }
            self._save_json(self.sessions_path, sessions)

    def _drop_session(self, token: str) -> None:
        with self._lock:
            sessions = self._load_json(self.sessions_path, {})
            sessions.pop(self._token_key(token), None)
            self._save_json(self.sessions_path, sessions)

    def _rate_state(self) -> dict[str, Any]:
        return self._load_json(self.rate_path, {"clients": {}})

    def _save_rate(self, state: dict[str, Any]) -> None:
        self._save_json(self.rate_path, state)

    def _is_locked(self, client_key: str) -> bool:
        with self._lock:
            state = self._rate_state()
            rec = state.get("clients", {}).get(client_key) or {}
            until = float(rec.get("locked_until") or 0)
            return until > time.time()

    def _register_failure(self, client_key: str) -> None:
        with self._lock:
            state = self._rate_state()
            clients = state.setdefault("clients", {})
            rec = clients.get(client_key) or {"failures": 0, "locked_until": 0}
            rec["failures"] = int(rec.get("failures") or 0) + 1
            rec["last_failure_at"] = time.time()
            if rec["failures"] >= MAX_FAILURES:
                rec["locked_until"] = time.time() + LOCKOUT_SECONDS
                rec["failures"] = 0
                self._drop_all_sessions_unlocked()
                self.owner._audit("AUTH_AUTO_LOCK", {"client": client_key})
            clients[client_key] = rec
            self._save_rate(state)

    def _drop_all_sessions_unlocked(self) -> None:
        self._save_json(self.sessions_path, {})

    def drop_all_sessions(self) -> None:
        with self._lock:
            self._drop_all_sessions_unlocked()

    def _clear_failures(self, client_key: str) -> None:
        with self._lock:
            state = self._rate_state()
            clients = state.setdefault("clients", {})
            clients.pop(client_key, None)
            self._save_rate(state)

    def _load_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default if not isinstance(default, dict) else dict(default)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default if not isinstance(default, dict) else dict(default)

    def _save_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
