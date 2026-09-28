"""IoT Mind — deep Internet-of-Things comprehension (offline, real knowledge).

Covers protocols, edge patterns, device identity, telemetry, security, and
Matter/Zigbee/MQTT/CoAP/Modbus/OPC-UA concepts. No fabricated device telemetry.
"""
from __future__ import annotations

import re
import time
from typing import Any


# Curated knowledge cards — concise, actionable, production-oriented
_IOT_CARDS: list[dict[str, Any]] = [
    {
        "id": "mqtt_qos",
        "topics": ["mqtt", "qos", "broker", "pubsub"],
        "title": "MQTT quality of service",
        "body": (
            "MQTT is a pub/sub protocol for constrained devices. QoS 0 = at most once, "
            "QoS 1 = at least once (dup possible), QoS 2 = exactly once (heavier). "
            "Prefer QoS 1 for critical telemetry with idempotent consumers; keep payloads small; "
            "use retained messages sparingly for last-known state; TLS + auth on the broker."
        ),
    },
    {
        "id": "edge_gateway",
        "topics": ["edge", "gateway", "fog", "offline"],
        "title": "Edge gateway pattern",
        "body": (
            "Devices talk local protocols (BLE/Zigbee/Modbus) to a gateway that normalizes "
            "telemetry, buffers offline, applies rules, and forwards via MQTT/HTTPS. "
            "Keep control loops that need <100ms on the edge; cloud is for fleet analytics "
            "and slow commands. Never block actuation on cloud round-trips."
        ),
    },
    {
        "id": "matter_thread",
        "topics": ["matter", "thread", "home", "chip"],
        "title": "Matter / Thread smart home",
        "body": (
            "Matter (CSA) standardizes application layer over Thread, Wi-Fi, Ethernet. "
            "Thread is IPv6 mesh (low power). Commissioning uses secure device attestation. "
            "Interoperability still depends on controller ecosystems; always verify clusters "
            "and vendor extensions before assuming full feature parity."
        ),
    },
    {
        "id": "zigbee_mesh",
        "topics": ["zigbee", "mesh", "coordinator", "enddevice"],
        "title": "Zigbee mesh roles",
        "body": (
            "Coordinator forms the network; routers extend mesh; end devices sleep. "
            "Binding and groups reduce hub chatter. Channel/interference and power supply "
            "quality dominate reliability. Bridge to IP via a trusted gateway with update policy."
        ),
    },
    {
        "id": "coap_rest",
        "topics": ["coap", "udp", "rest", "constrained"],
        "title": "CoAP for constrained REST",
        "body": (
            "CoAP maps REST verbs over UDP with confirmable messages and observe (push). "
            "Good for sleepy devices with DTLS. Pair with resource directories; watch NAT and "
            "firewall issues vs MQTT over TLS on 8883."
        ),
    },
    {
        "id": "modbus_ot",
        "topics": ["modbus", "plc", "ot", "scada", "opc"],
        "title": "Modbus / OPC-UA in OT",
        "body": (
            "Modbus TCP/RTU is simple register I/O — no auth historically; segment OT networks. "
            "OPC-UA adds information models, sessions, and stronger security profiles. "
            "Never expose bare Modbus to the internet; use DMZ historians and allow-lists."
        ),
    },
    {
        "id": "device_identity",
        "topics": ["identity", "mtls", "cert", "provision", "bootstrap"],
        "title": "Device identity & provisioning",
        "body": (
            "Each device needs unique credentials (X.509 or keyed bootstrap), rotatable secrets, "
            "and least-privilege topics/APIs. Prefer TPM/secure element when available. "
            "Just-in-time provisioning beats shared fleet passwords. Log attestations."
        ),
    },
    {
        "id": "telemetry_design",
        "topics": ["telemetry", "sensor", "timeseries", "schema"],
        "title": "Telemetry design",
        "body": (
            "Publish typed metrics with device_id, ts (UTC), unit, and quality flag. "
            "Batch high-frequency samples; send events for alarms. Schema-version payloads. "
            "Downsample at edge; keep raw bursts only when diagnosing. Validate ranges."
        ),
    },
    {
        "id": "digital_twin",
        "topics": ["twin", "shadow", "desired", "reported"],
        "title": "Digital twin / device shadow",
        "body": (
            "Separate desired vs reported state. Cloud writes desired; device reports actual; "
            "reconcile deltas. Version shadows; never assume desired applied without reported ack. "
            "Use this for safe remote config without blocking local control."
        ),
    },
    {
        "id": "iot_security",
        "topics": ["security", "firmware", "ota", "threat"],
        "title": "IoT security baseline",
        "body": (
            "Signed OTA, secure boot when possible, disable unused services, network segment, "
            "rotate certs, monitor anomalous traffic, and plan revoke/replace for compromised units. "
            "Physical access is in the threat model for field devices."
        ),
    },
    {
        "id": "ble_sensors",
        "topics": ["ble", "bluetooth", "beacon", "gatt"],
        "title": "BLE sensors",
        "body": (
            "BLE GATT suits phones/gateways nearby. Connection intervals vs battery trade off. "
            "Beacons broadcast IDs; apps resolve context. Encrypt bonds; watch OS background limits."
        ),
    },
    {
        "id": "pfai_iot_bridge",
        "topics": ["pfai", "agent", "control", "automation"],
        "title": "PFAI + IoT control plane",
        "body": (
            "PFAI reasons over IoT knowledge and policy; it does not invent live sensor values. "
            "Safe automation: propose rules → verify bounds → human/owner gate for destructive acts. "
            "Continuous learning may curate IoT Q&A; device commands stay explicitly authorized."
        ),
    },
]


class IoTMind:
    """Fast offline IoT understanding + grounded answers."""

    VERSION = "8.8.0"

    def __init__(self) -> None:
        self._queries = 0
        self._last: dict[str, Any] = {}

    def detect(self, message: str) -> dict[str, Any]:
        text = message or ""
        blob = text.lower()
        protocols = []
        for name, pat in [
            ("mqtt", r"mqtt"),
            ("coap", r"coap"),
            ("zigbee", r"zigbee"),
            ("ble", r"\bble\b|bluetooth"),
            ("matter", r"matter|thread"),
            ("modbus", r"modbus"),
            ("opcua", r"opc[\s-]?ua|opcua"),
            ("lora", r"lora|lorawan"),
        ]:
            if re.search(pat, blob, re.I):
                protocols.append(name)
        themes = []
        for name, pat in [
            ("security", r"أمن|security|tls|cert|ota|اختراق"),
            ("edge", r"edge|حافة|gateway|بوابة"),
            ("telemetry", r"telemetry|حساس|sensor|قياس|telemetry"),
            ("twin", r"twin|shadow|توأم"),
            ("mesh", r"mesh|شبكة\s*شبكية"),
            ("automation", r"أتمت|automat|تحكم|control|rule"),
        ]:
            if re.search(pat, blob, re.I):
                themes.append(name)
        iot_hit = bool(
            protocols
            or themes
            or re.search(
                r"iot|إنترنت\s*الأشياء|انترنت\s*الاشياء|أشياء|اشياء|"
                r"جهاز|أجهزة|اجهزة|sensor|actuator|plc|scada",
                text,
                re.I,
            )
        )
        return {
            "is_iot": iot_hit,
            "protocols": protocols,
            "themes": themes,
            "confidence": min(
                1.0,
                (0.55 if iot_hit else 0.0)
                + 0.12 * len(protocols)
                + 0.08 * len(themes),
            ),
        }

    def _rank_cards(self, message: str, det: dict[str, Any]) -> list[dict[str, Any]]:
        blob = (message or "").lower()
        keys = set(det.get("protocols") or []) | set(det.get("themes") or [])
        scored: list[tuple[float, dict]] = []
        for card in _IOT_CARDS:
            s = 0.0
            for t in card.get("topics") or []:
                if t in keys or t in blob:
                    s += 1.0
                if t in blob:
                    s += 0.5
            if det.get("is_iot") and card["id"] == "pfai_iot_bridge":
                s += 0.3
            if s > 0:
                scored.append((s, card))
        scored.sort(key=lambda x: x[0], reverse=True)
        if not scored and det.get("is_iot"):
            # General IoT overview
            return [_IOT_CARDS[1], _IOT_CARDS[7], _IOT_CARDS[9], _IOT_CARDS[11]]
        return [c for _, c in scored[:4]]

    def understand(self, message: str) -> dict[str, Any]:
        t0 = time.perf_counter_ns()
        det = self.detect(message)
        cards = self._rank_cards(message, det)
        self._queries += 1
        out = {
            "ok": True,
            "iot": True,
            "version": self.VERSION,
            "detection": det,
            "confidence": det.get("confidence"),
            "cards": [
                {"id": c["id"], "title": c["title"], "body": c["body"]} for c in cards
            ],
            "live_telemetry_invented": False,
            "elapsed_ns": time.perf_counter_ns() - t0,
            "note": "Offline IoT knowledge — no fabricated sensor readings.",
        }
        self._last = out
        return out

    def answer(self, message: str, *, language: str = "ar") -> dict[str, Any]:
        u = self.understand(message)
        cards = u.get("cards") or []
        ar = language.startswith("ar")
        if not u.get("detection", {}).get("is_iot") and not cards:
            text = (
                "لم أكتشف سؤالاً واضحاً عن إنترنت الأشياء — اذكر بروتوكولاً (MQTT/Zigbee/Matter) أو مشكلة أجهزة."
                if ar
                else "No clear IoT question detected — name a protocol (MQTT/Zigbee/Matter) or device problem."
            )
            return {**u, "answer": text, "grounded": False}
        parts = []
        if ar:
            parts.append("فهم IoT (معرفة مؤصّلة، بلا اختلاق قراءات حسّاسات):")
        else:
            parts.append("IoT understanding (grounded knowledge, no fabricated sensor values):")
        for c in cards:
            parts.append(f"• {c['title']}: {c['body']}")
        parts.append(
            "الأوامر على الأجهزة الحقيقية تبقى بصلاحية صريحة — التعلم المستمر يوسّع المعرفة فقط."
            if ar
            else "Real device commands stay explicitly authorized — continuous learning expands knowledge only."
        )
        return {**u, "answer": "\n".join(parts), "grounded": True}

    def training_seeds(self) -> list[dict[str, Any]]:
        """High-precision IoT examples for continuous curation."""
        rows = []
        for c in _IOT_CARDS:
            rows.append(
                {
                    "instruction": f"Explain {c['title']} for an IoT engineer.",
                    "response": c["body"],
                    "source": "iot_mind_seed",
                    "track": "software_engineering",
                    "metadata": {"iot_card": c["id"], "via": "iot_mind"},
                }
            )
        return rows

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "version": self.VERSION,
            "cards": len(_IOT_CARDS),
            "queries": self._queries,
            "last_confidence": (self._last.get("detection") or {}).get("confidence"),
            "live_telemetry_invented": False,
        }
