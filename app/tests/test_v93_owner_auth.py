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
        for k in ("PFAI_OWNER_EMAIL", "PFAI_OWNER_SECRET_HASH"):
            os.environ.pop(k, None)

    def tearDown(self):
        for k in ("PFAI_OWNER_EMAIL", "PFAI_OWNER_SECRET_HASH"):
            os.environ.pop(k, None)
        self.tmp.cleanup()

    def test_setup_once_then_blocked(self):
        self.assertTrue(self.auth.setup_required())
        ok = self.auth.run_setup("szz5462@gmail.com", STRONG, STRONG)
        self.assertTrue(ok["ok"])
        self.assertTrue(self.auth.setup_locked())
        self.assertFalse(self.auth.setup_required())
        again = self.auth.run_setup("evil@example.com", STRONG, STRONG)
        self.assertFalse(again["ok"])
        self.assertIn("disabled", again["error"])

    def test_setup_rejects_weak_and_mismatch(self):
        self.assertFalse(self.auth.run_setup("a@b.co", "short", "short")["ok"])
        self.assertFalse(self.auth.run_setup("a@b.co", STRONG, STRONG + "x")["ok"])

    def test_login_session_logout_and_expiry(self):
        self.auth.run_setup("owner@example.com", STRONG, STRONG)
        bad = self.auth.login("owner@example.com", "wrong-passcode!!", client_key="ip1")
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["error"], AUTH_FAIL_MESSAGE)
        # enumeration-safe: wrong email same message
        bad2 = self.auth.login("other@example.com", STRONG, client_key="ip1")
        self.assertEqual(bad2["error"], AUTH_FAIL_MESSAGE)

        good = self.auth.login("owner@example.com", STRONG, client_key="ip1")
        self.assertTrue(good["ok"])
        token = good["token"]
        self.assertEqual(self.auth.resolve_session(token), "owner@example.com")
        self.auth.logout(token)
        self.assertIsNone(self.auth.resolve_session(token))

        # expiry
        self.auth.session_ttl = 1
        tok2 = self.auth.login("owner@example.com", STRONG, client_key="ip2")["token"]
        time.sleep(1.2)
        self.assertIsNone(self.auth.resolve_session(tok2))

    def test_lockout_after_repeated_failures(self):
        self.auth.run_setup("owner@example.com", STRONG, STRONG)
        with mock.patch("pfai.owner_auth.MAX_FAILURES", 3), mock.patch("pfai.owner_auth.LOCKOUT_SECONDS", 60):
            for _ in range(3):
                self.auth.login("owner@example.com", "nope-nope-nope1", client_key="attacker")
            locked = self.auth.login("owner@example.com", STRONG, client_key="attacker")
            self.assertFalse(locked["ok"])
            self.assertTrue(locked.get("locked"))

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
        os.environ["PFAI_OWNER_EMAIL"] = "test-owner@example.invalid"
        os.environ["PFAI_OWNER_SECRET_HASH"] = hashlib.sha256(b"test-secret").hexdigest()
        os.environ.pop("ANTHROPIC_API_KEY", None)
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
        self.assertNotIn("passcode", body)
        self.assertNotIn("hash", str(body).lower())
        self.assertFalse(any(k in body for k in ("secret", "secret_hash", "token")))

    def test_legacy_header_still_works(self):
        r = self.client.get("/owner/identity", headers=self.headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["email"], "test-owner@example.invalid")

    def test_login_sets_httponly_cookie(self):
        r = self.client.post(
            "/owner/login",
            json={"email": "test-owner@example.invalid", "passcode": "test-secret"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["authenticated"])
        self.assertIn(COOKIE_NAME, r.cookies)
        # cookie auth without header
        r2 = self.client.get("/owner/identity")
        self.assertEqual(r2.status_code, 200)
        # logout
        r3 = self.client.post("/owner/logout")
        self.assertEqual(r3.status_code, 200)
        r4 = self.client.get("/owner/identity")
        self.assertEqual(r4.status_code, 401)

    def test_privilege_escalation_ignored(self):
        r = self.client.post(
            "/orchestrate?role=owner&admin=true",
            json={"goal": "x", "mode": "self_check", "context": {"role": "owner", "is_admin": True}},
        )
        self.assertEqual(r.status_code, 401)

    def test_setup_disabled_when_already_configured(self):
        r = self.client.post(
            "/owner/setup",
            json={"email": "hijack@example.com", "passcode": STRONG, "passcode_confirm": STRONG},
        )
        self.assertIn(r.status_code, (400, 409))
        self.assertNotIn(STRONG, r.text)

    def test_uniform_auth_failure(self):
        r = self.client.post(
            "/owner/login",
            json={"email": "nobody@example.com", "passcode": "Definitely-Wrong-99!"},
        )
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["detail"], AUTH_FAIL_MESSAGE)

    def test_dashboard_still_public(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("تسجيل دخول المالك", r.text)
        self.assertNotIn("test-secret", r.text)


class TestFirstTimeSetupIsolatedAPI(unittest.TestCase):
    """Fresh credential root via patched OWNER_AUTH paths is heavy; service-level covers setup.
    Here we only assert setup endpoint rejects when configured (no takeover).
    """

    def test_cannot_take_over_via_setup(self):
        os.environ.setdefault("PFAI_OWNER_EMAIL", "test-owner@example.invalid")
        os.environ.setdefault(
            "PFAI_OWNER_SECRET_HASH", hashlib.sha256(b"test-secret").hexdigest()
        )
        from pfai.api import app

        client = TestClient(app)
        r = client.post(
            "/owner/setup",
            json={
                "email": "szz5462@gmail.com",
                "passcode": STRONG,
                "passcode_confirm": STRONG,
            },
        )
        self.assertNotEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
