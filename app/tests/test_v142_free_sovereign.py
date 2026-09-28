"""PFAI 8.9 — free sovereign integrity: audit, self-repair, productive freedom."""
from __future__ import annotations

import hashlib
import os
import unittest

from pfai.deep_comprehension import comprehend
from pfai.free_sovereign import FreeSovereignIntegrity
from pfai.interfaces.self_check import HealProposal, HealResult, SelfCheckReport


class TestFreeSovereignUnit(unittest.TestCase):
    def test_cycle_repairs_schema_and_heals(self):
        state = {"pending": 2, "current": 1, "healed": False}

        def check():
            return SelfCheckReport(
                ok=state["pending"] == 0,
                checks=[
                    {"name": "schema_up_to_date", "ok": state["pending"] == 0, "detail": {}},
                    {"name": "runtime_health", "ok": True, "detail": {}},
                ],
                summary="ok" if state["pending"] == 0 else "failures_detected",
            )

        def propose(report):
            steps = [] if report.ok else ["clear_transient_cache"]
            return HealProposal(
                proposal_id="p1",
                diagnosis="test",
                safe=True,
                reversible=True,
                steps=steps,
                requires_owner=False,
            )

        def apply(pid):
            state["healed"] = True
            return HealResult(ok=True, proposal_id=pid, applied=True, message="applied")

        def mig_status():
            return {"pending_count": state["pending"], "current": state["current"], "target": 5, "pending": ["v2"]}

        def mig_apply():
            state["pending"] = 0
            state["current"] = 5
            return {"ok": True, "current": 5, "applied": ["v2", "v3", "v4", "v5"]}

        sov = FreeSovereignIntegrity(
            self_check_fn=check,
            heal_propose_fn=propose,
            heal_apply_fn=apply,
            migrate_status_fn=mig_status,
            migrate_apply_fn=mig_apply,
            continuous_ensure_fn=lambda: {"ok": True, "worker_alive": True},
            evolution_ensure_fn=lambda: {"ok": True, "alive": True},
            open_status_fn=lambda: {
                "open_chat_tools": True,
                "auto_accept_learning": True,
                "auto_safe_heal": True,
                "still_gated": ["model_weight_promotion"],
            },
            conflict_scan_fn=lambda: {"ok": True, "conflicts": []},
        )
        before = sov.audit()
        self.assertFalse(before["ok"])
        out = sov.sovereign_cycle(deep_code=False)
        self.assertTrue(out["ok"])
        self.assertTrue(out["improved"])
        self.assertEqual(out["after"]["schema_current"], 5)
        self.assertEqual(out["after"]["schema_pending"], 0)
        self.assertIn("model_weight_promotion", out["freedom"]["still_hard_gated"])

    def test_comprehension_free_sovereign(self):
        u = comprehend("راجع كل شيء بدقة وامنحه صلاحية كاملة بلا اي قيود كذكاء حر")
        self.assertEqual(u["intent"], "free_sovereign")


class TestFreeSovereignAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PFAI_OWNER_USERNAME"] = "testowner"
        os.environ["PFAI_OWNER_PASSWORD_HASH"] = hashlib.sha256(b"test-secret").hexdigest()
        os.environ["PFAI_PUBLIC_ACCESS_MODE"] = "1"
        os.environ["PFAI_OPEN_CHAT_TOOLS"] = "1"
        os.environ["PFAI_AUTO_ACCEPT_LEARNING"] = "1"
        os.environ["PFAI_AUTO_SAFE_HEAL"] = "1"
        os.environ["PFAI_CONTINUOUS_TRAINING_ENABLED"] = "true"
        os.environ["PFAI_EVOLVE_MINUTE_SECONDS"] = "3600"
        os.environ.pop("ANTHROPIC_API_KEY", None)
        from fastapi.testclient import TestClient
        from pfai.api import app, runtime, COMMAND_AGENT, EVOLUTION, FREE_SOVEREIGN
        from pfai.model import EchoProvider

        runtime.model = EchoProvider()
        COMMAND_AGENT.model = runtime.model
        cls.client = TestClient(app)
        cls.EVOLUTION = EVOLUTION
        cls.FREE = FREE_SOVEREIGN

    @classmethod
    def tearDownClass(cls):
        try:
            cls.EVOLUTION.stop("test")
        except Exception:
            pass

    def test_version_89(self):
        from pfai import __version__

        self.assertTrue(__version__.startswith("8."))
        self.assertEqual(self.client.get("/health").json().get("version"), __version__)

    def test_tools_present(self):
        names = {t["name"] for t in self.client.get("/chat/tools").json()["tools"]}
        for n in ("free_sovereign_cycle", "free_sovereign_audit", "free_ai_status", "self_heal_cycle"):
            self.assertIn(n, names)

    def test_audit_and_cycle(self):
        r = self.client.get("/chat/tools")
        self.assertEqual(r.status_code, 200)
        # Direct tool via sovereign instance
        audit = self.FREE.audit()
        self.assertIn("self_check", audit)
        self.assertIn("freedom", audit)
        cycle = self.FREE.sovereign_cycle(deep_code=False)
        self.assertIn("repair", cycle)
        self.assertEqual(cycle.get("weight_promotion"), "never_auto")

    def test_chat_arabic_sovereign(self):
        r = self.client.post(
            "/chat/message",
            json={
                "message": "راجع كل شيء بدقة عالية وامنحه صلاحية كاملة بلا اي قيود كذكاء حر يصلح الاعطال",
                "language": "ar",
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertNotEqual(body.get("status"), "waiting_for_approval")
        tools = {t.get("tool") for t in (body.get("tools") or [])}
        self.assertTrue(
            tools.intersection({"free_sovereign_cycle", "free_ai_status", "self_heal_cycle", "self_check_run"}),
            tools,
        )


if __name__ == "__main__":
    unittest.main()
