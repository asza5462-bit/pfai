"""PFAI 8.8 — quantum-inspired ultra-fast core + IoT mind + evolution cadence."""
from __future__ import annotations

import hashlib
import os
import tempfile
import time
import unittest

from pfai.deep_comprehension import comprehend
from pfai.evolution_cadence import EvolutionCadence
from pfai.iot_mind import IoTMind
from pfai.quantum_core import QuantumInspiredCore


class TestQuantumCore(unittest.TestCase):
    def test_pulse_is_classical_and_fast(self):
        core = QuantumInspiredCore(
            iot_fn=lambda m: {"confidence": 0.9, "ok": True},
            continuous_status_fn=lambda: {"worker_alive": True, "smart": {"enabled": True}},
            evolve_status_fn=lambda: {"alive": True, "minute_ticks": 1},
        )
        out = core.pulse("أريد سرعة كمّية و MQTT")
        self.assertTrue(out["ok"])
        self.assertFalse(out["quantum_hardware"])
        self.assertTrue(out["quantum_inspired"])
        self.assertIn("timing", out)
        # Local parallel pulse should stay well under 200ms on CI
        self.assertLess(out["timing"]["elapsed_ms"], 200)
        self.assertGreaterEqual(len(out["superposition"]), 3)

    def test_hot_route_microsecond_band_possible(self):
        core = QuantumInspiredCore()
        # Warm once
        core.hot_route("ping")
        r = core.hot_route("سرعة فائقة")
        self.assertTrue(r["ok"])
        self.assertFalse(r["quantum_hardware"])
        # Hot route is tiny; allow millisecond slack on busy hosts
        self.assertLess(r["timing"]["elapsed_ms"], 50)


class TestIoTMind(unittest.TestCase):
    def test_mqtt_grounded(self):
        mind = IoTMind()
        ans = mind.answer("اشرح MQTT QoS للأجهزة المقيدة", language="ar")
        self.assertTrue(ans["grounded"])
        self.assertTrue(ans["detection"]["is_iot"])
        self.assertIn("mqtt", ans["detection"]["protocols"])
        self.assertFalse(ans["live_telemetry_invented"])
        self.assertIn("QoS", ans["answer"] + str(ans.get("cards")))

    def test_seeds_nonempty(self):
        seeds = IoTMind().training_seeds()
        self.assertGreaterEqual(len(seeds), 8)
        self.assertTrue(all(s.get("instruction") and s.get("response") for s in seeds))


class TestEvolutionCadence(unittest.TestCase):
    def test_minute_tick_and_status(self):
        hits = {"m": 0}

        def minute():
            hits["m"] += 1
            return {"ok": True}

        evo = EvolutionCadence(
            minute_fn=minute,
            hour_fn=lambda: {"ok": True},
            day_fn=lambda: {"ok": True},
            minute_seconds=60,
            hour_seconds=3600,
            day_seconds=86400,
        )
        out = evo.tick_minute()
        self.assertTrue(out.get("ok"))
        self.assertEqual(hits["m"], 1)
        st = evo.status()
        self.assertEqual(st["minute_ticks"], 1)
        self.assertEqual(st["weight_promotion"], "never_auto")
        evo.stop("test")


class TestComprehension(unittest.TestCase):
    def test_quantum_iot_intent(self):
        u = comprehend("اريد ذكاء اصطناعي كمي فائق ويفهم انترنت الاشياء بسرعة جزء من مليون")
        self.assertEqual(u["intent"], "quantum_iot_speed")
        self.assertIn("iot", u.get("entities") or [])


class TestQuantumAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PFAI_OWNER_USERNAME"] = "testowner"
        os.environ["PFAI_OWNER_PASSWORD_HASH"] = hashlib.sha256(b"test-secret").hexdigest()
        os.environ["PFAI_PUBLIC_ACCESS_MODE"] = "1"
        os.environ["PFAI_OPEN_CHAT_TOOLS"] = "1"
        os.environ["PFAI_CONTINUOUS_TRAINING_ENABLED"] = "true"
        os.environ["PFAI_QUANTUM_CORE"] = "1"
        os.environ["PFAI_EVOLUTION_CADENCE"] = "1"
        # Slow cadence in tests — avoid background hammering
        os.environ["PFAI_EVOLVE_MINUTE_SECONDS"] = "3600"
        os.environ["PFAI_EVOLVE_HOUR_SECONDS"] = "7200"
        os.environ["PFAI_EVOLVE_DAY_SECONDS"] = "86400"
        os.environ.pop("ANTHROPIC_API_KEY", None)
        from fastapi.testclient import TestClient
        from pfai.api import app, runtime, COMMAND_AGENT, EVOLUTION
        from pfai.model import EchoProvider

        runtime.model = EchoProvider()
        COMMAND_AGENT.model = runtime.model
        cls.client = TestClient(app)
        cls.EVOLUTION = EVOLUTION

    @classmethod
    def tearDownClass(cls):
        try:
            cls.EVOLUTION.stop("test_teardown")
        except Exception:
            pass

    def test_version_88(self):
        from pfai import __version__

        self.assertTrue(__version__.startswith("8.8"))
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("version"), __version__)

    def test_tools_registered(self):
        r = self.client.get("/chat/tools")
        names = {t["name"] for t in r.json()["tools"]}
        for n in ("quantum_pulse", "quantum_status", "iot_understand", "evolution_status", "evolution_tick"):
            self.assertIn(n, names)

    def test_chat_quantum_iot_arabic(self):
        r = self.client.post(
            "/chat/message",
            json={
                "message": "اريد ذكاء كمي فائق ويفهم انترنت الاشياء بسرعة جزء من مليون ويتطور كل دقيقة",
                "language": "ar",
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertNotEqual(body.get("status"), "waiting_for_approval")
        tools = {t.get("tool") for t in (body.get("tools") or [])}
        self.assertTrue(
            tools.intersection({"quantum_pulse", "iot_understand", "evolution_status", "quantum_status"}),
            tools,
        )
        # Message must be forwarded into IoT/quantum tools
        for t in body.get("tools") or []:
            if t.get("tool") == "iot_understand" and t.get("ok"):
                res = t.get("result") or {}
                self.assertTrue((res.get("detection") or {}).get("is_iot") or res.get("grounded"))
            if t.get("tool") == "quantum_pulse" and t.get("ok"):
                res = t.get("result") or {}
                self.assertFalse(res.get("quantum_hardware"))
                self.assertIn("timing", res)


if __name__ == "__main__":
    unittest.main()
