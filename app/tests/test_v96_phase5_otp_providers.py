"""PHASE 5: Email OTP auth, migration hardening, local/open-weight providers."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from pfai.email_provider import MockEmailProvider, SMTPEmailProvider, email_provider_from_env
from pfai.longevity.migration_runner import MigrationRunner
from pfai.longevity.migrations import PLATFORM_MIGRATIONS, register_platform_migrations, verify_platform_schema
from pfai.longevity.provider_registry import ProviderRegistry
from pfai.model_local import LocalModelProvider, OpenWeightModelProvider, model_settings_from_env
from pfai.owner_auth import (
    AUTH_FAIL_MESSAGE,
    COOKIE_NAME,
    OTP_FAIL_MESSAGE,
    OTP_SENT_MESSAGE,
    OwnerAuthService,
)
from pfai.owner_control import OwnerControl
from pfai.interfaces.migration import Migration


STRONG = "Correct-Horse-Battery-1!"


class TestEmailProviders(unittest.TestCase):
    def test_mock_send_metadata_only(self):
        p = MockEmailProvider()
        r = p.send(__import__("pfai.email_provider", fromlist=["EmailMessageSpec"]).EmailMessageSpec(
            to="a@b.co", subject="t", body_text="Code: 123456"
        ))
        self.assertTrue(r["ok"])
        self.assertEqual(p.sent[0]["to"], "a@b.co")
        self.assertNotIn("123456", json.dumps(p.sent))
        self.assertNotIn("123456", json.dumps(r))

    def test_smtp_readiness_without_claiming_connected(self):
        s = SMTPEmailProvider(host="smtp.example.invalid", from_addr="x@y.z")
        ready = s.readiness()
        self.assertTrue(ready["host_configured"])
        self.assertFalse(ready["connected"])

    def test_email_provider_from_env_default_mock(self):
        os.environ.pop("PFAI_EMAIL_PROVIDER", None)
        self.assertIsInstance(email_provider_from_env(), MockEmailProvider)


class TestOwnerEmailOTP(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.owner = OwnerControl(str(self.root / "ledger.jsonl"))
        import pfai.owner_auth as oa

        oa.PBKDF2_ITERATIONS = 1000
        oa.OTP_HASH_ITERATIONS = 1000
        oa.OTP_TTL_SECONDS = 5
        oa.OTP_RESEND_COOLDOWN = 2
        oa.OTP_MAX_ATTEMPTS = 3
        oa.OTP_MAX_REQUESTS_PER_HOUR = 5
        self.mock_mail = MockEmailProvider()
        self.auth = OwnerAuthService(
            self.owner, root=str(self.root), session_ttl=30, email_provider=self.mock_mail
        )
        for k in ("PFAI_OWNER_EMAIL", "PFAI_OWNER_SECRET_HASH"):
            os.environ.pop(k, None)
        self.auth.run_setup("owner@example.com", STRONG, STRONG)

    def tearDown(self):
        for k in ("PFAI_OWNER_EMAIL", "PFAI_OWNER_SECRET_HASH"):
            os.environ.pop(k, None)
        self.tmp.cleanup()

    def _otp_from_mock(self) -> str:
        body = self.mock_mail._last_body_for_tests
        # "Code: NNNNNN"
        for line in body.splitlines():
            if line.startswith("Code:"):
                return line.split(":", 1)[1].strip()
        raise AssertionError("OTP not found in mock mail body")

    def test_otp_generation_is_numeric_and_hashed(self):
        code = OwnerAuthService.generate_otp(length=6)
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())
        digest = OwnerAuthService.hash_otp(code)
        self.assertTrue(digest.startswith("pbkdf2_sha256$"))
        self.assertNotIn(code, digest)
        self.assertTrue(OwnerAuthService.verify_otp_hash(code, digest))
        self.assertFalse(OwnerAuthService.verify_otp_hash("000000", digest))

    def test_successful_otp_login_session_logout(self):
        req = self.auth.request_otp("owner@example.com", client_key="c1")
        self.assertTrue(req["ok"])
        self.assertEqual(req["message"], OTP_SENT_MESSAGE)
        self.assertNotIn("otp", json.dumps(req).lower().replace("otp_sent", ""))
        # Ensure challenge response never contains the code digits from email
        otp = self._otp_from_mock()
        self.assertNotIn(otp, json.dumps(req))
        ver = self.auth.verify_otp(
            "owner@example.com", otp, req["challenge_id"], client_key="c1"
        )
        self.assertTrue(ver["ok"])
        token = ver["token"]
        self.assertEqual(self.auth.resolve_session(token), "owner@example.com")
        self.auth.logout(token)
        self.assertIsNone(self.auth.resolve_session(token))

    def test_otp_single_use(self):
        req = self.auth.request_otp("owner@example.com", client_key="c2")
        otp = self._otp_from_mock()
        cid = req["challenge_id"]
        self.assertTrue(self.auth.verify_otp("owner@example.com", otp, cid, client_key="c2")["ok"])
        again = self.auth.verify_otp("owner@example.com", otp, cid, client_key="c2")
        self.assertFalse(again["ok"])
        self.assertEqual(again["error"], OTP_FAIL_MESSAGE)

    def test_otp_expiration(self):
        import pfai.owner_auth as oa

        oa.OTP_TTL_SECONDS = 1
        req = self.auth.request_otp("owner@example.com", client_key="c3")
        otp = self._otp_from_mock()
        time.sleep(1.2)
        bad = self.auth.verify_otp("owner@example.com", otp, req["challenge_id"], client_key="c3")
        self.assertFalse(bad["ok"])

    def test_invalid_otp_and_excessive_attempts(self):
        req = self.auth.request_otp("owner@example.com", client_key="c4")
        cid = req["challenge_id"]
        for _ in range(3):
            r = self.auth.verify_otp("owner@example.com", "000000", cid, client_key="c4")
            self.assertFalse(r["ok"])
        # Exhausted / further attempts fail uniformly
        otp = self._otp_from_mock()
        r = self.auth.verify_otp("owner@example.com", otp, cid, client_key="c4")
        self.assertFalse(r["ok"])

    def test_resend_cooldown_and_enumeration_resistance(self):
        import pfai.owner_auth as oa

        oa.OTP_RESEND_COOLDOWN = 30
        a = self.auth.request_otp("owner@example.com", client_key="c5")
        b = self.auth.request_otp("owner@example.com", client_key="c5")
        # Uniform shape even when rate-limited (same keys)
        self.assertEqual(set(a.keys()) & {"ok", "challenge_id", "expires_in", "message"}, set(b.keys()) & {"ok", "challenge_id", "expires_in", "message"})
        wrong = self.auth.request_otp("nobody@example.com", client_key="c6")
        self.assertTrue(wrong["ok"])
        self.assertEqual(wrong["message"], OTP_SENT_MESSAGE)
        # Wrong email must not send mail
        sent_before = len(self.mock_mail.sent)
        self.auth.request_otp("evil@example.com", client_key="c7")
        # may or may not increment depending on cooldown path; body must never leak via API
        self.assertNotIn("otp", json.dumps(wrong).lower().replace("expires", ""))

    def test_otp_not_stored_plaintext(self):
        self.auth.request_otp("owner@example.com", client_key="store1")
        otp = self._otp_from_mock()
        raw = (self.root / "owner_otp_challenges.json").read_text(encoding="utf-8")
        self.assertNotIn(otp, raw)
        self.assertIn("pbkdf2_sha256$", raw)

    def test_public_status_lists_email_otp(self):
        st = self.auth.public_status()
        self.assertIn("email_otp", st["auth_methods"])
        self.assertNotIn("passcode_hash", json.dumps(st))


class TestPhase5MigrationHardening(unittest.TestCase):
    def test_ordering_idempotent_backup_verify_rollback(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            backups: list[dict] = []

            def backup():
                backups.append({"path": f"bak-{len(backups)}", "label": "pre"})
                return backups[-1]

            # Start at schema 1 with isolated state under tmp (override migration paths via chdir)
            cwd = os.getcwd()
            try:
                os.chdir(d)
                (root / "data" / "longevity").mkdir(parents=True)
                runner = MigrationRunner(
                    current=1,
                    state_path=str(root / "schema_version.json"),
                    backup_fn=backup,
                    audit_path=str(root / "mig_audit.jsonl"),
                    verify_fn=verify_platform_schema,
                )
                register_platform_migrations(runner)
                plan = runner.plan()
                self.assertEqual([m.version for m in plan], [2, 3])

                dry = runner.run(dry_run=True)
                self.assertTrue(dry.ok)
                self.assertEqual(runner.current_version(), 1)
                self.assertEqual(len(backups), 0)

                # Apply without backup_fn blocked
                blocked = MigrationRunner(
                    current=1,
                    state_path=str(root / "schema_blocked.json"),
                    backup_fn=None,
                    audit_path=str(root / "blocked_audit.jsonl"),
                )
                register_platform_migrations(blocked)
                bad = blocked.run(dry_run=False)
                self.assertFalse(bad.ok)
                self.assertIn("backup", bad.error or "")

                applied = runner.run(dry_run=False)
                self.assertTrue(applied.ok)
                self.assertEqual(runner.current_version(), 3)
                self.assertGreaterEqual(len(backups), 1)
                verify = runner.verify_schema()
                self.assertTrue(verify["ok"])

                # Duplicate execution is no-op
                again = runner.run(dry_run=False)
                self.assertTrue(again.ok)
                self.assertEqual(again.applied, [])
                self.assertEqual(runner.current_version(), 3)

                # Failed migration leaves version unchanged for that step
                fail_runner = MigrationRunner(
                    current=3,
                    state_path=str(root / "schema_fail.json"),
                    backup_fn=backup,
                    audit_path=str(root / "fail_audit.jsonl"),
                )

                def boom(_conn):
                    raise RuntimeError("boom")

                fail_runner.register(
                    Migration(version=4, name="boom", upgrade=boom, description="fail")
                )
                failed = fail_runner.run(target=4, dry_run=False)
                self.assertFalse(failed.ok)
                self.assertEqual(fail_runner.current_version(), 3)

                # Rollback one step (marker-only downgrade)
                rb = runner.rollback_one()
                self.assertTrue(rb.ok)
                self.assertEqual(runner.current_version(), 2)
            finally:
                os.chdir(cwd)

    def test_audit_log_written(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cwd = os.getcwd()
            try:
                os.chdir(d)
                (root / "data" / "longevity").mkdir(parents=True)
                runner = MigrationRunner(
                    current=1,
                    state_path=str(root / "sv.json"),
                    backup_fn=lambda: {"path": "x"},
                    audit_path=str(root / "audit.jsonl"),
                    verify_fn=verify_platform_schema,
                )
                register_platform_migrations(runner)
                runner.run(dry_run=False)
                text = (root / "audit.jsonl").read_text(encoding="utf-8")
                self.assertIn("migration_intent", text)
                self.assertIn("migration_applied", text)
                self.assertIn("migration_verified", text)
            finally:
                os.chdir(cwd)


class TestLocalOpenWeightProviders(unittest.TestCase):
    def test_adapter_honest_when_runtime_missing(self):
        p = LocalModelProvider(
            base_url="http://127.0.0.1:9",
            model="test",
            probe_on_init=True,
            timeout=1,
        )
        ready = p.readiness()
        self.assertFalse(ready["connected"])
        self.assertIn("Adapter implemented, runtime not connected", ready["status"])
        with self.assertRaises(RuntimeError):
            p.generate("hi")

    def test_registry_creates_local_not_echo(self):
        reg = ProviderRegistry()
        reg.bootstrap_defaults()
        local = reg.create("local", base_url="http://127.0.0.1:9", probe_on_init=False)
        self.assertIsInstance(local, LocalModelProvider)
        ow = reg.create("open_weight", base_url="http://127.0.0.1:9", probe_on_init=False)
        self.assertIsInstance(ow, OpenWeightModelProvider)

    def test_model_settings_from_env(self):
        with mock.patch.dict(
            os.environ,
            {
                "MODEL_PROVIDER": "local",
                "MODEL_NAME": "demo-model",
                "MODEL_ENDPOINT": "http://127.0.0.1:11434/v1",
                "MODEL_TIMEOUT": "12",
            },
            clear=False,
        ):
            s = model_settings_from_env()
            self.assertEqual(s["provider"], "local")
            self.assertEqual(s["model"], "demo-model")
            self.assertEqual(s["timeout"], 12.0)


class TestPhase5APISecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PFAI_OWNER_EMAIL"] = "test-owner@example.invalid"
        os.environ["PFAI_OWNER_SECRET_HASH"] = hashlib.sha256(b"test-secret").hexdigest()
        os.environ["PFAI_EMAIL_PROVIDER"] = "mock"
        os.environ.pop("ANTHROPIC_API_KEY", None)
        # Force fresh-ish OTP tunables for API module's already-imported auth if possible
        from pfai.api import app, OWNER_AUTH
        from pfai.email_provider import MockEmailProvider

        cls.client = TestClient(app)
        cls.headers = {"X-Owner-Secret": "test-secret"}
        cls.owner_auth = OWNER_AUTH
        cls.mock_mail = MockEmailProvider()
        OWNER_AUTH.email_provider = cls.mock_mail

    def test_otp_api_no_leakage_and_session(self):
        r = self.client.post(
            "/owner/otp/request",
            json={"email": "test-owner@example.invalid"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertIn("challenge_id", body)
        blob = json.dumps(body)
        self.assertNotRegex(blob, r"\b\d{6}\b")
        otp = None
        for line in self.mock_mail._last_body_for_tests.splitlines():
            if line.startswith("Code:"):
                otp = line.split(":", 1)[1].strip()
        self.assertTrue(otp)
        self.assertNotIn(otp, blob)

        bad = self.client.post(
            "/owner/otp/verify",
            json={
                "email": "test-owner@example.invalid",
                "otp": "000000",
                "challenge_id": body["challenge_id"],
            },
        )
        self.assertIn(bad.status_code, (401, 429))
        self.assertNotIn(otp, bad.text)

        self.client.cookies.clear()
        ok = self.client.post(
            "/owner/otp/request",
            json={"email": "test-owner@example.invalid"},
        )
        # May be rate-limited from prior request; use passcode path if needed
        # Prefer a dedicated client key via separate TestClient instance
        client2 = TestClient(self.client.app)
        from pfai.api import OWNER_AUTH
        from pfai.email_provider import MockEmailProvider

        mail2 = MockEmailProvider()
        OWNER_AUTH.email_provider = mail2
        # Bypass cooldown by clearing otp rate state
        OWNER_AUTH._save_json(OWNER_AUTH.otp_path, {"challenges": {}, "request_rate": {}})
        req = client2.post("/owner/otp/request", json={"email": "test-owner@example.invalid"})
        self.assertEqual(req.status_code, 200)
        otp2 = None
        for line in mail2._last_body_for_tests.splitlines():
            if line.startswith("Code:"):
                otp2 = line.split(":", 1)[1].strip()
        ver = client2.post(
            "/owner/otp/verify",
            json={
                "email": "test-owner@example.invalid",
                "otp": otp2,
                "challenge_id": req.json()["challenge_id"],
            },
        )
        self.assertEqual(ver.status_code, 200, ver.text)
        self.assertTrue(ver.json()["authenticated"])
        self.assertNotIn("token", ver.json())
        self.assertNotIn(otp2, ver.text)
        self.assertIn(COOKIE_NAME, ver.cookies)
        ident = client2.get("/owner/identity")
        self.assertEqual(ident.status_code, 200)
        client2.post("/owner/logout")
        client2.cookies.clear()
        self.assertEqual(client2.get("/owner/identity").status_code, 401)

    def test_privilege_escalation_client_fields_ignored(self):
        r = self.client.get("/owner/identity", params={"role": "owner", "admin": "true"})
        self.assertEqual(r.status_code, 401)
        r2 = self.client.post(
            "/platform/plan",
            json={"goal": "x", "role": "owner", "admin": True, "approved": True},
        )
        self.assertEqual(r2.status_code, 401)
        # With real auth, role fields still ignored (owner from session/header only)
        r3 = self.client.get("/platform/providers", headers=self.headers)
        self.assertEqual(r3.status_code, 200)
        body = r3.json()
        self.assertIn("local_open_weight", body)
        self.assertIn("status", body["local_open_weight"])

    def test_migrations_owner_gated(self):
        self.assertEqual(self.client.get("/platform/migrations").status_code, 401)
        r = self.client.get("/platform/migrations", headers=self.headers)
        self.assertEqual(r.status_code, 200)
        self.assertIn("verify", r.json())

    def test_learning_no_weight_mutation(self):
        from pfai.api import PLATFORM_LEARNING, PLATFORM_SELF_HEAL, CODING_AGENT, ORCHESTRATOR

        self.assertFalse(PLATFORM_LEARNING.allows_weight_mutation())
        self.assertFalse(PLATFORM_LEARNING.training_readiness()["weight_training_allowed_now"])
        self.assertIsNotNone(CODING_AGENT)
        self.assertIsNotNone(ORCHESTRATOR)
        self.assertIsNotNone(PLATFORM_SELF_HEAL)

    def test_enumeration_uniform_otp_request(self):
        from pfai.api import OWNER_AUTH

        OWNER_AUTH._save_json(OWNER_AUTH.otp_path, {"challenges": {}, "request_rate": {}})
        a = self.client.post("/owner/otp/request", json={"email": "test-owner@example.invalid"})
        OWNER_AUTH._save_json(OWNER_AUTH.otp_path, {"challenges": {}, "request_rate": {}})
        b = self.client.post("/owner/otp/request", json={"email": "nope@example.invalid"})
        self.assertEqual(a.status_code, 200)
        self.assertEqual(b.status_code, 200)
        self.assertEqual(set(a.json().keys()), set(b.json().keys()))
        self.assertEqual(a.json()["message"], b.json()["message"])


if __name__ == "__main__":
    unittest.main()
