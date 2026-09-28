"""Open Chat Tool Execution — unlock locks in public/open mode; keep suite gated."""
import hashlib
import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from pfai.authorized_execution import risk_to_permission
from pfai.interfaces.tools import ToolPermission
from pfai.open_execution import open_chat_tools
from pfai.tool_router import ToolRouter, ToolSpec


class TestRiskMappingDeployList(unittest.TestCase):
    def test_deployments_list_is_read_not_production(self):
        self.assertEqual(
            risk_to_permission("read", name="deployments_list", requires_approval=False),
            ToolPermission.READ,
        )

    def test_forget_still_data_delete(self):
        self.assertEqual(
            risk_to_permission("sensitive", name="forget_memory", requires_approval=True),
            ToolPermission.DATA_DELETE,
        )


class TestOpenChatToolsFlag(unittest.TestCase):
    def test_off_when_public_access_zero(self):
        with mock.patch.dict(os.environ, {"PFAI_PUBLIC_ACCESS_MODE": "0", "PFAI_OPEN_CHAT_TOOLS": "", "PFAI_ENV": "test"}, clear=False):
            self.assertFalse(open_chat_tools())

    def test_on_when_public_access_one(self):
        with mock.patch.dict(os.environ, {"PFAI_PUBLIC_ACCESS_MODE": "1", "PFAI_OPEN_CHAT_TOOLS": ""}, clear=False):
            self.assertTrue(open_chat_tools())

    def test_explicit_open_overrides(self):
        with mock.patch.dict(os.environ, {"PFAI_PUBLIC_ACCESS_MODE": "0", "PFAI_OPEN_CHAT_TOOLS": "1"}, clear=False):
            self.assertTrue(open_chat_tools())


class TestToolRouterUnlock(unittest.TestCase):
    def test_sensitive_executes_when_open(self):
        calls = {"n": 0}

        def start():
            calls["n"] += 1
            return {"status": "running"}

        router = ToolRouter(
            {"continuous_start": start},
            specs=[ToolSpec("continuous_start", "start", "sensitive", True, {})],
        )
        with mock.patch.dict(os.environ, {"PFAI_OPEN_CHAT_TOOLS": "1"}, clear=False):
            self.assertFalse(router.requires_approval("continuous_start"))
            cat = {t["name"]: t for t in router.catalog()}
            self.assertFalse(cat["continuous_start"]["requires_approval"])
            ok = router.execute("continuous_start", {}, approved=False)
            self.assertTrue(ok.get("ok"), ok)
            self.assertEqual(calls["n"], 1)

    def test_sensitive_blocked_when_closed(self):
        calls = {"n": 0}

        def start():
            calls["n"] += 1
            return {"status": "running"}

        router = ToolRouter(
            {"continuous_start": start},
            specs=[ToolSpec("continuous_start", "start", "sensitive", True, {})],
        )
        with mock.patch.dict(os.environ, {"PFAI_OPEN_CHAT_TOOLS": "0", "PFAI_PUBLIC_ACCESS_MODE": "0"}, clear=False):
            self.assertTrue(router.requires_approval("continuous_start"))
            blocked = router.execute("continuous_start", {}, approved=False)
            self.assertTrue(blocked.get("needs_approval"))
            self.assertEqual(calls["n"], 0)


class TestOpenChatAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PFAI_OWNER_USERNAME"] = "testowner"
        os.environ["PFAI_OWNER_PASSWORD_HASH"] = hashlib.sha256(b"test-secret").hexdigest()
        os.environ["PFAI_PUBLIC_ACCESS_MODE"] = "1"
        os.environ["PFAI_OPEN_CHAT_TOOLS"] = "1"
        os.environ.pop("ANTHROPIC_API_KEY", None)
        from pfai.api import app, runtime, COMMAND_AGENT
        from pfai.model import EchoProvider
        runtime.model = EchoProvider()
        COMMAND_AGENT.model = runtime.model
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        os.environ["PFAI_PUBLIC_ACCESS_MODE"] = "0"
        os.environ.pop("PFAI_OPEN_CHAT_TOOLS", None)
        os.environ.pop("PFAI_OWNER_USERNAME", None)
        os.environ.pop("PFAI_OWNER_PASSWORD_HASH", None)

    def test_chat_tools_zero_locks(self):
        r = self.client.get("/chat/tools")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body.get("open_chat_tools"))
        self.assertEqual(body.get("locked_count"), 0)
        self.assertFalse(any(t.get("requires_approval") for t in body.get("tools") or []))

    def test_continuous_start_no_approval_wait(self):
        r = self.client.post(
            "/chat/message",
            json={"message": "start continuous learning now", "language": "en"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertNotEqual(body.get("status"), "waiting_for_approval")
        tools = {t.get("tool") for t in (body.get("tools") or [])}
        # May include continuous_start and/or continuous_status depending on planner
        self.assertTrue(tools.intersection({"continuous_start", "continuous_status", "system_status"}) or body.get("status") == "completed")

    def test_assets_show_open_banner(self):
        js = self.client.get("/assets/chat.js")
        self.assertEqual(js.status_code, 200)
        self.assertIn("open_chat_tools", js.text)
        self.assertIn("Fully open", js.text)
        root = self.client.get("/")
        self.assertIn("chatOpenStatus", root.text)
        from pathlib import Path
        self.assertIn("Apache License", Path("/agent/pfai/pfai/LICENSE").read_text(encoding="utf-8")[:80])


if __name__ == "__main__":
    unittest.main()
