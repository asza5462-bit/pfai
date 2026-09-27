"""PHASE 14 authorized defensive testing — bounded, rate-limited, DENY without auth."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pfai.authorized_execution import sanitize_args
from pfai.engineering.secure_analyzer import SecureCodeAnalyzer
from pfai.engineering.target_authorization import TargetAuthorizationGate
from pfai.engineering.types import new_id
from pfai.elite.web_fabric import validate_url_for_fetch


SECURITY_HEADERS = (
    "content-security-policy",
    "strict-transport-security",
    "x-content-type-options",
    "x-frame-options",
    "referrer-policy",
    "permissions-policy",
)


class AuthorizedSecurityTester:
    """Active checks only after TargetAuthorizationGate ALLOW."""

    def __init__(
        self,
        gate: TargetAuthorizationGate | None = None,
        *,
        audit_path: str = "data/longevity/engineering/authorized_testing_audit.jsonl",
    ) -> None:
        self.gate = gate or TargetAuthorizationGate()
        self.audit_path = Path(audit_path)
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self._timestamps: list[float] = []

    def _audit(self, event: str, **detail: Any) -> None:
        row = {"ts": time.time(), "event": event, **sanitize_args(detail)}
        with self.audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _rate_ok(self, limit: int) -> bool:
        now = time.time()
        self._timestamps = [t for t in self._timestamps if now - t < 60]
        if len(self._timestamps) >= int(limit):
            return False
        self._timestamps.append(now)
        return True

    def run(
        self,
        target: str,
        *,
        declaration: str = "",
        scope: str = "",
        approved: bool = False,
        actor: str = "",
        allow_external: bool = False,
        allowed_actions: list[str] | None = None,
    ) -> dict[str, Any]:
        auth = self.gate.require_authorized(
            target,
            declaration=declaration,
            scope=scope,
            approved=approved,
            actor=actor,
            allow_external=allow_external,
            allowed_actions=allowed_actions
            or ["passive_inspect", "security_headers", "static_analysis"],
        )
        if not auth.get("ok"):
            self._audit("testing_denied", target=target, error=auth.get("error"), decision=auth.get("decision"))
            return {
                "ok": False,
                "denied": True,
                "decision": auth.get("decision") or "DENY",
                "error": auth.get("error") or "unauthorized",
                "findings": [],
            }

        classified = auth.get("classification") or {}
        findings: list[dict[str, Any]] = []
        actions = list((auth.get("scope") or {}).get("allowed_actions") or [])
        rate = int(auth.get("rate_limit_per_minute") or 30)
        timeout = float(auth.get("timeout_seconds") or 10)

        # Local path: static analysis only
        if classified.get("kind") == "local_path":
            analyzer = SecureCodeAnalyzer(classified.get("path") or target)
            result = analyzer.analyze()
            findings.extend(result.get("findings") or [])
            self._audit("local_static_analysis", target=target, finding_count=len(findings))
            return {
                "ok": True,
                "mode": "local_static",
                "authorized": True,
                "findings": findings,
                "authorization": {"decision": "ALLOW", "target_id": (auth.get("scope") or {}).get("target_id")},
            }

        # URL: passive HTTP configuration / headers only — no exploit payloads
        if "passive_inspect" not in actions and "security_headers" not in actions:
            return {
                "ok": False,
                "error": "action_not_in_scope",
                "denied": True,
                "findings": [],
            }
        if not self._rate_ok(rate):
            return {"ok": False, "error": "rate_limited", "findings": []}

        url = classified.get("url") or target
        check = validate_url_for_fetch(url, allow_private=bool(classified.get("local")))
        if not check.get("ok"):
            self._audit("ssrf_block", target=url, error=check.get("error"))
            return {"ok": False, "error": check.get("error"), "findings": [], "ssrf_blocked": True}

        try:
            req = urllib.request.Request(
                url,
                method="GET",
                headers={"User-Agent": "PFAI-AuthorizedDefense/14", "Accept": "text/html,application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                headers = {k.lower(): v for k, v in resp.headers.items()}
                body = resp.read(64_000)
            missing = [h for h in SECURITY_HEADERS if h not in headers]
            for h in missing:
                findings.append(
                    {
                        "finding_id": new_id("find"),
                        "category": "missing_security_headers",
                        "severity": "medium",
                        "confidence": 0.85,
                        "affected_component": urlparse(url).path or "/",
                        "evidence": f"Response missing header: {h}",
                        "explanation": f"Security header `{h}` not present on authorized target response.",
                        "remediation": f"Configure `{h}` on the HTTP service.",
                        "verification_status": "open",
                    }
                )
            # TLS hint
            if urlparse(url).scheme != "https" and not classified.get("local"):
                findings.append(
                    {
                        "finding_id": new_id("find"),
                        "category": "insecure_configuration",
                        "severity": "medium",
                        "confidence": 0.9,
                        "affected_component": url,
                        "evidence": "scheme=http",
                        "explanation": "Non-HTTPS endpoint observed for non-local authorized target.",
                        "remediation": "Serve over HTTPS with HSTS where appropriate.",
                        "verification_status": "open",
                    }
                )
            self._audit("passive_http_inspect", target=url, missing_headers=missing, bytes=len(body))
            return {
                "ok": True,
                "mode": "passive_http",
                "authorized": True,
                "findings": findings,
                "headers_observed": sorted(headers.keys())[:40],
                "authorization": {"decision": "ALLOW"},
            }
        except urllib.error.HTTPError as exc:
            self._audit("http_error", target=url, code=exc.code)
            return {"ok": False, "error": f"http_{exc.code}", "findings": findings, "authorized": True}
        except Exception as exc:
            self._audit("fetch_error", target=url, error=type(exc).__name__)
            return {"ok": False, "error": type(exc).__name__, "findings": findings, "authorized": True}
