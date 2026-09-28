"""PHASE 5 (post Email-OTP removal): passcode auth, migration hardening, local providers."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from pfai.email_provider import email_config_report
from pfai.longevity.migration_runner import MigrationRunner
from pfai.longevity.migrations import PLATFORM_MIGRATIONS, register_platform_migrations, verify_platform_schema
from pfai.longevity.provider_registry import ProviderRegistry
from pfai.model_local import LocalModelProvider, OpenWeightModelProvider, model_settings_from_env
from pfai.owner_auth import (
    AUTH_FAIL_MESSAGE,
    COOKIE_NAME,
    OwnerAuthService,
)
from pfai.owner_control import OwnerControl
from pfai.interfaces.migration import Migration


STRONG = "Correct-Horse-Battery-1!"


class TestEmailOtpRemoved(unittest.TestCase):
    def test_email_config_report_removed(self):
        report = email_config_report()
        self.assertEqual(report["EMAIL_DELIVERY_STATUS"], "REMOVED")
        self.assertEqual(report["EMAIL_OTP"], "REMOVED")
        self.assertFalse(report["EMAIL_PRODUCTION_READY"])
        self.assertFalse(report["endpoint_configured"])
        self.assertFalse(report["api_key_configured"])


class TestOwnerPasscodeAuth(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.owner = OwnerControl(str(self.root / "ledger.jsonl"))
        import pfai.owner_auth as oa

        oa.PBKDF2_ITERATIONS = 1000
        self.auth = OwnerAuthService(self.owner, root=str(self.root), session_ttl=30)
        for k in ("PFAI_OWNER_USERNAME", "PFAI_OWNER_SECRET_HASH"):
            os.environ.pop(k, None)
        self.auth.run_setup("owneruser", STRONG, STRONG)

    def tearDown(self):
        for k in ("PFAI_OWNER_USERNAME", "PFAI_OWNER_SECRET_HASH"):
            os.environ.pop(k, None)
        self.tmp.cleanup()

    def test_passcode_login_session_logout(self):
        ver = self.auth.login("owneruser", STRONG, client_key="c1")
        self.assertTrue(ver["ok"])
        token = ver["token"]
        self.assertEqual(self.auth.resolve_session(token), "owneruser")
        self.auth.logout(token)
        self.assertIsNone(self.auth.resolve_session(token))

    def test_bad_passcode_fails_uniformly(self):
        bad = self.auth.login("owneruser", "wrong-passcode!!", client_key="c2")
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["error"], AUTH_FAIL_MESSAGE)

    def test_otp_apis_removed_from_service(self):
        self.assertFalse(hasattr(self.auth, "request_otp"))
        self.assertFalse(hasattr(self.auth, "verify_otp"))
        self.assertFalse(hasattr(self.auth, "generate_otp"))

    def test_public_status_lists_passcode_not_email_otp(self):
        st = self.auth.public_status()
        self.assertIn("password", st["auth_methods"])
        self.assertNotIn("email_otp", st["auth_methods"])
        self.assertEqual(st.get("email_otp"), "REMOVED")
        self.assertNotIn("password_hash", json.dumps(st))
        self.assertNotIn("email_config", st)


class TestPhase5MigrationHardening(unittest.TestCase):
    def test_ordering_idempotent_backup_verify_rollback(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            backups: list[dict] = []

            def backup():
                backups.append({"path": f"bak-{len(backups)}", "label": "pre"})
                return backups[-1]

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
                self.assertEqual([m.version for m in plan], [2, 3, 4, 5])

                dry = runner.run(dry_run=True)
                self.assertTrue(dry.ok)
                self.assertEqual(runner.current_version(), 1)
                self.assertEqual(len(backups), 0)

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
                self.assertEqual(runner.current_version(), 5)
                self.assertGreaterEqual(len(backups), 1)
                verify = runner.verify_schema()
                self.assertTrue(verify["ok"])

                again = runner.run(dry_run=False)
                self.assertTrue(again.ok)
                self.assertEqual(again.applied, [])
                self.assertEqual(runner.current_version(), 5)

                fail_runner = MigrationRunner(
                    current=5,
                    state_path=str(root / "schema_fail.json"),
                    backup_fn=backup,
                    audit_path=str(root / "fail_audit.jsonl"),
                )

                def boom(_conn):
                    raise RuntimeError("boom")

                fail_runner.register(
                    Migration(version=6, name="boom", upgrade=boom, description="fail")
                )
                failed = fail_runner.run(target=6, dry_run=False)
                self.assertFalse(failed.ok)
                self.assertEqual(fail_runner.current_version(), 5)

                rb = runner.rollback_one()
                self.assertTrue(rb.ok)
                self.assertEqual(runner.current_version(), 4)
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
        os.environ["PFAI_OWNER_USERNAME"] = "testowner"
        os.environ["PFAI_OWNER_SECRET_HASH"] = hashlib.sha256(b"test-secret").hexdigest()
        os.environ.pop("ANTHROPIC_API_KEY", None)
        # TestClient is HTTP — production Secure cookies would not be stored.
        os.environ["PFAI_ENV"] = "test"
        os.environ["PFAI_COOKIE_SECURE"] = "false"
        from pfai.api import app, OWNER_AUTH

        cls.client = TestClient(app)
        cls.headers = {"X-Owner-Secret": "test-secret"}
        cls.owner_auth = OWNER_AUTH

    def test_otp_routes_gone(self):
        r = self.client.post("/owner/otp/request", json={"username": "testowner"})
        self.assertEqual(r.status_code, 404)
        r2 = self.client.post(
            "/owner/otp/verify",
            json={"username": "testowner", "otp": "000000", "challenge_id": "x"},
        )
        self.assertEqual(r2.status_code, 404)

    def test_passcode_login_session(self):
        # Ensure passcode path works via legacy SHA-256 env hash
        client = TestClient(self.client.app)
        bad = client.post(
            "/owner/login",
            json={"username": "testowner", "password": "wrong-secret"},
        )
        self.assertIn(bad.status_code, (401, 429))
        ok = client.post(
            "/owner/login",
            json={"username": "testowner", "password": "test-secret"},
        )
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertTrue(ok.json()["authenticated"])
        self.assertNotIn("token", ok.json())
        self.assertIn(COOKIE_NAME, ok.cookies)
        ident = client.get("/owner/identity")
        self.assertEqual(ident.status_code, 200)
        client.post("/owner/logout")
        client.cookies.clear()
        self.assertEqual(client.get("/owner/identity").status_code, 401)

    def test_privilege_escalation_client_fields_ignored(self):
        r = self.client.get("/owner/identity", params={"role": "owner", "admin": "true"})
        self.assertEqual(r.status_code, 401)
        r2 = self.client.post(
            "/platform/plan",
            json={"goal": "x", "role": "owner", "admin": True, "approved": True},
        )
        self.assertEqual(r2.status_code, 401)
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


if __name__ == "__main__":
    unittest.main()
