"""Owner authentication: setup, login, session, lockout, privilege escalation."""
from __future__ import annotations

import hashlib
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from pfai.owner_auth import OwnerAuthService, AUTH_FAIL_MESSAGE, COOKIE_NAME
from pfai.owner_control import OwnerControl


STRONG = "Correct-Horse-Battery-1!"
OWNER_USER = "testowner"


class TestOwnerAuthService(unittest.TestCase):
    def setUp(self):
        os.environ["PFAI_OWNER_PBKDF2_ITERATIONS"] = "1000"
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.owner = OwnerControl(str(self.root / "ledger.jsonl"))
        # Re-import iterations used at hash time — OwnerAuthService reads PBKDF2_ITERATIONS at module load.
        import pfai.owner_auth as oa

        oa.PBKDF2_ITERATIONS = 1000
        self.auth = OwnerAuthService(self.owner, root=str(self.root), session_ttl=2)
        for k in ("PFAI_OWNER_USERNAME", "PFAI_OWNER_EMAIL", "PFAI_OWNER_PASSWORD_HASH"):
            os.environ.pop(k, None)

    def tearDown(self):
        for k in ("PFAI_OWNER_USERNAME", "PFAI_OWNER_EMAIL", "PFAI_OWNER_PASSWORD_HASH"):
            os.environ.pop(k, None)
        self.tmp.cleanup()

    def test_setup_once_then_blocked(self):
        self.assertTrue(self.auth.setup_required())
        ok = self.auth.run_setup(OWNER_USER, STRONG, STRONG)
        self.assertTrue(ok["ok"])
        self.assertTrue(self.auth.setup_locked())
        self.assertFalse(self.auth.setup_required())
        again = self.auth.run_setup("eviluser", STRONG, STRONG)
        self.assertFalse(again["ok"])
        self.assertIn("disabled", again["error"])

    def test_setup_rejects_weak_mismatch_and_email(self):
        self.assertFalse(self.auth.run_setup("ab", "short", "short")["ok"])
        self.assertFalse(self.auth.run_setup(OWNER_USER, STRONG, STRONG + "x")["ok"])
        self.assertFalse(self.auth.run_setup("owner@example.com", STRONG, STRONG)["ok"])

    def test_login_session_logout_and_expiry(self):
        self.auth.run_setup(OWNER_USER, STRONG, STRONG)
        bad = self.auth.login(OWNER_USER, "wrong-password!!", client_key="ip1")
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["error"], AUTH_FAIL_MESSAGE)
        # enumeration-safe: wrong username same message
        bad2 = self.auth.login("otheruser", STRONG, client_key="ip1")
        self.assertEqual(bad2["error"], AUTH_FAIL_MESSAGE)

        good = self.auth.login(OWNER_USER, STRONG, client_key="ip1")
        self.assertTrue(good["ok"])
        token = good["token"]
        self.assertEqual(self.auth.resolve_session(token), OWNER_USER)
        self.auth.logout(token)
        self.assertIsNone(self.auth.resolve_session(token))

        # expiry
        self.auth.session_ttl = 1
        tok2 = self.auth.login(OWNER_USER, STRONG, client_key="ip2")["token"]
        time.sleep(1.2)
        self.assertIsNone(self.auth.resolve_session(tok2))

    def test_lockout_after_repeated_failures(self):
        self.auth.run_setup(OWNER_USER, STRONG, STRONG)
        tok = self.auth.login(OWNER_USER, STRONG, client_key="legit")["token"]
        self.assertEqual(self.auth.resolve_session(tok), OWNER_USER)
        with mock.patch("pfai.owner_auth.MAX_FAILURES", 3), mock.patch("pfai.owner_auth.LOCKOUT_SECONDS", 60):
            for _ in range(3):
                self.auth.login(OWNER_USER, "nope-nope-nope1", client_key="attacker")
            locked = self.auth.login(OWNER_USER, STRONG, client_key="attacker")
            self.assertFalse(locked["ok"])
            self.assertTrue(locked.get("locked"))
            # Auto-lock revokes existing sessions
            self.assertIsNone(self.auth.resolve_session(tok))

    def test_absolute_session_auto_lock(self):
        self.auth.run_setup(OWNER_USER, STRONG, STRONG)
        self.auth.session_ttl = 60
        self.auth.session_abs_max = 1
        tok = self.auth.login(OWNER_USER, STRONG, client_key="ip-abs")["token"]
        time.sleep(1.2)
        self.assertIsNone(self.auth.resolve_session(tok))

    def test_hash_never_contains_plaintext(self):
        digest = OwnerAuthService.hash_passcode(STRONG)
        self.assertTrue(digest.startswith("pbkdf2_sha256$"))
        self.assertNotIn(STRONG, digest)
        self.assertTrue(OwnerAuthService.verify_passcode(STRONG, digest))
        legacy = OwnerControl.hash_secret(STRONG)
        self.assertTrue(OwnerControl.verify_secret(STRONG, legacy))


class TestOwnerAuthAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PFAI_OWNER_USERNAME"] = OWNER_USER
        os.environ.pop("PFAI_OWNER_EMAIL", None)
        os.environ["PFAI_OWNER_PASSWORD_HASH"] = hashlib.sha256(b"test-secret").hexdigest()
        os.environ.pop("ANTHROPIC_API_KEY", None)
        # TestClient is HTTP — production Secure cookies would not be stored.
        os.environ["PFAI_ENV"] = "test"
        os.environ["PFAI_COOKIE_SECURE"] = "false"
        from pfai.api import app

        cls.client = TestClient(app)
        cls.headers = {"X-Owner-Secret": "test-secret"}

    def test_public_health_and_status(self):
        h = self.client.get("/health")
        self.assertEqual(h.status_code, 200)
        st = self.client.get("/owner/status")
        self.assertEqual(st.status_code, 200)
        body = st.json()
        self.assertIn("setup_required", body)
        self.assertIn("authenticated", body)
        self.assertIn("password", body.get("auth_methods", []))
        self.assertEqual(body.get("email_otp"), "REMOVED")
        self.assertEqual(body.get("email_auth"), "REMOVED")
        self.assertNotIn("passcode", body)
        self.assertNotIn("hash", str(body).lower())
        self.assertFalse(any(k in body for k in ("secret", "secret_hash", "token")))

    def test_legacy_header_still_works(self):
        r = self.client.get("/owner/identity", headers=self.headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["username"], OWNER_USER)

    def test_login_sets_httponly_cookie(self):
        r = self.client.post(
            "/owner/login",
            json={"username": OWNER_USER, "password": "test-secret"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["authenticated"])
        self.assertEqual(r.json()["username"], OWNER_USER)
        self.assertNotIn("token", r.json())
        self.assertNotIn("password", r.json())
        self.assertNotIn("secret_hash", r.json())
        self.assertIn(COOKIE_NAME, r.cookies)
        # Starlette/httpx exposes set-cookie; assert security flags when present.
        set_cookie = r.headers.get("set-cookie") or ""
        self.assertIn(COOKIE_NAME, set_cookie)
        self.assertIn("httponly", set_cookie.lower())
        self.assertIn("samesite=strict", set_cookie.lower().replace(" ", ""))
        # cookie auth without header
        r2 = self.client.get("/owner/identity")
        self.assertEqual(r2.status_code, 200)
        # logout
        r3 = self.client.post("/owner/logout")
        self.assertEqual(r3.status_code, 200)
        self.client.cookies.clear()
        r4 = self.client.get("/owner/identity")
        self.assertEqual(r4.status_code, 401)

    def test_wrong_username_401(self):
        r = self.client.post(
            "/owner/login",
            json={"username": "wronguser", "password": "test-secret"},
        )
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["detail"], AUTH_FAIL_MESSAGE)

    def test_wrong_password_401(self):
        r = self.client.post(
            "/owner/login",
            json={"username": OWNER_USER, "password": "Definitely-Wrong-99!"},
        )
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["detail"], AUTH_FAIL_MESSAGE)

    def test_secure_cookie_flags_helper(self):
        from pfai import api as api_mod
        from starlette.requests import Request

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 123),
            "server": ("test", 443),
        }
        req = Request(scope)
        prev_env = os.environ.get("PFAI_ENV")
        prev_cookie = os.environ.get("PFAI_COOKIE_SECURE")
        try:
            # HTTPS request with no cookie override → Secure must be true.
            os.environ.pop("PFAI_COOKIE_SECURE", None)
            os.environ["PFAI_ENV"] = "test"
            flags = api_mod._secure_cookie_flags(req)
            self.assertTrue(flags["httponly"])
            self.assertTrue(flags["secure"])
            self.assertEqual(flags["samesite"], "strict")
        finally:
            if prev_cookie is None:
                os.environ.pop("PFAI_COOKIE_SECURE", None)
            else:
                os.environ["PFAI_COOKIE_SECURE"] = prev_cookie
            if prev_env is None:
                os.environ.pop("PFAI_ENV", None)
            else:
                os.environ["PFAI_ENV"] = prev_env

    def test_secure_cookie_production_forces_secure(self):
        from pfai import api as api_mod
        from starlette.requests import Request

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 123),
            "server": ("test", 80),
        }
        req = Request(scope)
        prev_env = os.environ.get("PFAI_ENV")
        prev_cookie = os.environ.get("PFAI_COOKIE_SECURE")
        try:
            os.environ["PFAI_ENV"] = "production"
            os.environ["PFAI_COOKIE_SECURE"] = "false"
            flags = api_mod._secure_cookie_flags(req)
            self.assertTrue(flags["secure"])
        finally:
            if prev_env is None:
                os.environ.pop("PFAI_ENV", None)
            else:
                os.environ["PFAI_ENV"] = prev_env
            if prev_cookie is None:
                os.environ.pop("PFAI_COOKIE_SECURE", None)
            else:
                os.environ["PFAI_COOKIE_SECURE"] = prev_cookie

    def test_secure_cookie_dev_http_explicit(self):
        from pfai import api as api_mod
        from starlette.requests import Request

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 123),
            "server": ("test", 80),
        }
        req = Request(scope)
        prev_env = os.environ.get("PFAI_ENV")
        prev_cookie = os.environ.get("PFAI_COOKIE_SECURE")
        try:
            os.environ.pop("PFAI_ENV", None)
            os.environ["PFAI_COOKIE_SECURE"] = "false"
            flags = api_mod._secure_cookie_flags(req)
            self.assertFalse(flags["secure"])
        finally:
            if prev_env is None:
                os.environ.pop("PFAI_ENV", None)
            else:
                os.environ["PFAI_ENV"] = prev_env
            if prev_cookie is None:
                os.environ.pop("PFAI_COOKIE_SECURE", None)
            else:
                os.environ["PFAI_COOKIE_SECURE"] = prev_cookie

    def test_public_observability_has_no_secrets(self):
        self.client.cookies.clear()
        for path in ("/health", "/system", "/metrics", "/modules", "/deployments", "/continuous/status"):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, msg=path)
            body = r.text.lower()
            for needle in ("pbkdf2", "api_key", "password=", "owner_secret", "pfai_owner_session="):
                self.assertNotIn(needle, body, msg=f"{path} leaked {needle}")
            if path in ("/recovery/verify", "/research/verify"):
                self.assertNotIn("history_path", body)
                self.assertNotIn("ledger_path", body)

    def test_private_read_endpoints_require_owner(self):
        self.client.cookies.clear()
        self.assertEqual(self.client.get("/knowledge/search?q=x").status_code, 401)
        self.assertEqual(self.client.get("/regression/pending").status_code, 401)
        headers = {"X-Owner-Secret": "test-secret"}
        self.assertEqual(self.client.get("/knowledge/search?q=x", headers=headers).status_code, 200)
        self.assertEqual(self.client.get("/regression/pending", headers=headers).status_code, 200)

    def test_recovery_verify_sanitizes_paths(self):
        r = self.client.get("/recovery/verify")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("valid", data)
        self.assertIn("history_name", data)
        self.assertNotIn("history_path", data)
        self.assertNotIn("/", data["history_name"])
        r2 = self.client.get("/research/verify")
        self.assertEqual(r2.status_code, 200)
        data2 = r2.json()
        self.assertIn("ledger_name", data2)
        self.assertNotIn("ledger_path", data2)

    def test_owner_endpoints_reject_public_url_alone(self):
        self.client.cookies.clear()
        from pfai.api import app
        import inspect
        from fastapi.params import Depends as DependsParam

        owner_paths = []
        for route in app.routes:
            path = getattr(route, "path", None)
            endpoint = getattr(route, "endpoint", None)
            if not path or not endpoint:
                continue
            sig = inspect.signature(endpoint)
            uses_owner = False
            for p in sig.parameters.values():
                if p.default is inspect.Parameter.empty:
                    continue
                dep = getattr(p.default, "dependency", None)
                if callable(dep) and getattr(dep, "__name__", "") == "require_owner":
                    uses_owner = True
                if isinstance(p.default, DependsParam) and getattr(p.default.dependency, "__name__", "") == "require_owner":
                    uses_owner = True
            if uses_owner:
                owner_paths.append(path)

        self.assertGreaterEqual(len(owner_paths), 40)
        for method, path in [
            ("POST", "/orchestrate"),
            ("POST", "/chat/message"),
            ("GET", "/coding/tracks"),
            ("POST", "/platform/learning"),
            ("GET", "/owner/identity"),
            ("POST", "/continuous/promote/x"),
        ]:
            if method == "GET":
                r = self.client.get(path)
            else:
                r = self.client.request(method, path, json={"goal": "x", "message": "x", "content": "x"})
            self.assertIn(r.status_code, (401, 503, 422), msg=f"{method} {path} -> {r.status_code}")

    def test_privilege_escalation_ignored(self):
        self.client.cookies.clear()
        r = self.client.post(
            "/orchestrate?role=owner&admin=true",
            json={"goal": "x", "mode": "self_check", "context": {"role": "owner", "is_admin": True}},
        )
        self.assertEqual(r.status_code, 401)

    def test_setup_disabled_when_already_configured(self):
        r = self.client.post(
            "/owner/setup",
            json={"username": "hijackuser", "password": STRONG, "password_confirm": STRONG},
        )
        self.assertIn(r.status_code, (400, 409))
        self.assertNotIn(STRONG, r.text)

    def test_uniform_auth_failure(self):
        r = self.client.post(
            "/owner/login",
            json={"username": "nobody", "password": "Definitely-Wrong-99!"},
        )
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["detail"], AUTH_FAIL_MESSAGE)

    def test_dashboard_still_public(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("تسجيل دخول المالك", r.text)
        self.assertIn("اسم المستخدم", r.text)
        self.assertNotIn("ownerEmail", r.text)
        self.assertNotIn("type=\"email\"", r.text)
        self.assertNotIn("test-secret", r.text)


class TestFirstTimeSetupIsolatedAPI(unittest.TestCase):
    """Fresh credential root via patched OWNER_AUTH paths is heavy; service-level covers setup.
    Here we only assert setup endpoint rejects when configured (no takeover).
    """

    def test_cannot_take_over_via_setup(self):
        os.environ.setdefault("PFAI_OWNER_USERNAME", OWNER_USER)
        os.environ.pop("PFAI_OWNER_EMAIL", None)
        os.environ.setdefault(
            "PFAI_OWNER_PASSWORD_HASH", hashlib.sha256(b"test-secret").hexdigest()
        )
        from pfai.api import app

        client = TestClient(app)
        r = client.post(
            "/owner/setup",
            json={
                "username": "takeover",
                "password": STRONG,
                "password_confirm": STRONG,
            },
        )
        self.assertNotEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
