"""Public Access Mode: no login/OTP; public UI+chat; privileged ops blocked."""
from __future__ import annotations

import hashlib
import os
import sqlite3
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


class TestPublicAccessMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PFAI_PUBLIC_ACCESS_MODE"] = "1"
        os.environ["PFAI_ENV"] = "test"
        os.environ["PFAI_COOKIE_SECURE"] = "false"
        os.environ.pop("ANTHROPIC_API_KEY", None)
        # Import after env so module-level flags that read env at call-time still work;
        # public_access_mode() reads env dynamically.
        from pfai import api as api_mod

        # Force re-bind of app under public mode (functions read env at request time).
        cls.api_mod = api_mod
        # Do not raise server exceptions — /ask may 500 without ANTHROPIC_API_KEY;
        # we only assert auth is not required.
        cls.client = TestClient(api_mod.app, raise_server_exceptions=False)

    @classmethod
    def tearDownClass(cls):
        os.environ["PFAI_PUBLIC_ACCESS_MODE"] = "0"

    def test_root_ui_public_no_login(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("الوصول العام", r.text)
        self.assertNotIn("ownerModal", r.text)
        self.assertNotIn("ownerUsername", r.text)
        self.assertNotIn('type="email"', r.text)
        self.assertNotIn("تسجيل دخول المالك", r.text)

    def test_owner_status_public_access(self):
        st = self.client.get("/owner/status")
        self.assertEqual(st.status_code, 200)
        body = st.json()
        self.assertTrue(body.get("public_access"))
        self.assertEqual(body.get("authentication"), "DISABLED")
        self.assertFalse(body.get("login_required"))
        self.assertEqual(body.get("email_otp"), "REMOVED")
        self.assertEqual(body.get("auth_methods"), [])

    def test_login_and_otp_disabled(self):
        self.assertEqual(
            self.client.post(
                "/owner/login", json={"username": "x", "password": "Definitely-Wrong-99!"}
            ).status_code,
            410,
        )
        self.assertEqual(self.client.post("/owner/otp/request", json={}).status_code, 404)
        self.assertEqual(self.client.post("/owner/otp/verify", json={}).status_code, 404)

    def test_public_chat_and_ask_without_auth(self):
        # No cookies / no owner header
        self.client.cookies.clear()
        r = self.client.post("/chat/message", json={"message": "مرحبا", "language": "ar"})
        self.assertIn(r.status_code, (200, 422, 500), r.text)
        # 500 only if provider missing; must NOT be 401/403
        self.assertNotIn(r.status_code, (401, 403, 410))
        ask = self.client.post("/ask", json={"question": "ping"})
        self.assertNotIn(ask.status_code, (401, 403))

    def test_public_health_and_tools(self):
        h = self.client.get("/health")
        self.assertEqual(h.status_code, 200)
        self.assertTrue(h.json().get("public_access"))
        self.assertEqual(self.client.get("/chat/tools").status_code, 200)
        self.assertEqual(self.client.get("/modules").status_code, 200)
        self.assertEqual(self.client.get("/system").status_code, 200)

    def test_no_auth_cookie_required(self):
        self.client.cookies.clear()
        r = self.client.get("/coding/tracks")
        self.assertNotIn(r.status_code, (401, 403))

    def test_privileged_endpoints_not_public(self):
        self.client.cookies.clear()
        # Even with forged secret header — public mode forbids privileged ops.
        headers = {"X-Owner-Secret": "test-secret"}
        cases = [
            ("POST", "/deploy/canary", {"version": "x", "traffic": 0.1}),
            ("POST", "/deploy/promote/x", {}),
            ("POST", "/deploy/rollback/x", {}),
            ("POST", "/platform/training/cycle", {"owner_requested": True}),
            ("POST", "/platform/training/rollback", {"reason": "x"}),
            ("POST", "/continuous/promote/x", {}),
            ("POST", "/platform/models/model-v0007/activate", {}),
            ("GET", "/owner/identity", None),
        ]
        for method, path, body in cases:
            if method == "GET":
                r = self.client.get(path, headers=headers)
            else:
                r = self.client.request(method, path, json=body or {}, headers=headers)
            self.assertEqual(r.status_code, 403, msg=f"{method} {path} -> {r.status_code} {r.text}")

    def test_models_lkg_intact(self):
        db = Path("data/longevity/training_phase9_verify/models/model_registry.sqlite3")
        con = sqlite3.connect(db)
        self.assertEqual(con.execute("select model_id from model_active").fetchone()[0], "model-v0007")
        self.assertEqual(con.execute("select model_id from model_lkg").fetchone()[0], "model-v0001")


if __name__ == "__main__":
    unittest.main()
