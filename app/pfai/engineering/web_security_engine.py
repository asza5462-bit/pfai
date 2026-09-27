"""PHASE 17 Web Application Security Engine — defensive, evidence-based, safe verification."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pfai.authorized_execution import sanitize_args
from pfai.engineering.secure_analyzer import SecureCodeAnalyzer
from pfai.engineering.types import Severity, new_id

try:
    from pfai.engineering.authorized_testing import SECURITY_HEADERS as _HDRS
except Exception:  # pragma: no cover
    _HDRS = (
        "content-security-policy",
        "strict-transport-security",
        "x-content-type-options",
        "x-frame-options",
        "referrer-policy",
        "permissions-policy",
    )


# CWE hints for common categories (informational)
_CWE_MAP = {
    "secret_exposure": "CWE-798",
    "injection_risk": "CWE-89",
    "xss_risk": "CWE-79",
    "csrf_risk": "CWE-352",
    "ssrf_risk": "CWE-918",
    "path_traversal": "CWE-22",
    "insecure_cors": "CWE-942",
    "insecure_deserialization": "CWE-502",
    "weak_input_validation": "CWE-20",
    "missing_security_headers": "CWE-693",
    "insecure_cookie": "CWE-614",
    "auth_weakness": "CWE-287",
    "access_control": "CWE-639",
    "information_disclosure": "CWE-209",
}


_EXTRA_RULES: list[dict[str, Any]] = [
    {
        "category": "csrf_risk",
        "severity": Severity.MEDIUM.value,
        "confidence": 0.55,
        "pattern": re.compile(r"(?i)csrf(_token)?\s*=\s*None|csrf_exempt|@csrf_exempt|SameSite\s*=\s*None"),
        "explanation": "Possible CSRF protection disabled or weakened.",
        "remediation": "Enable CSRF tokens; set SameSite=Lax/Strict on cookies.",
        "impact": "Cross-site state-changing requests may succeed.",
    },
    {
        "category": "insecure_cookie",
        "severity": Severity.MEDIUM.value,
        "confidence": 0.7,
        "pattern": re.compile(r"(?i)set_cookie\([^\)]*secure\s*=\s*False|Set-Cookie:[^\n]*((?!Secure).)*$"),
        "explanation": "Cookie may be set without Secure flag.",
        "remediation": "Set Secure; HttpOnly; SameSite on session cookies.",
        "impact": "Session cookie may leak over cleartext.",
    },
    {
        "category": "auth_weakness",
        "severity": Severity.HIGH.value,
        "confidence": 0.65,
        "pattern": re.compile(r"(?i)password\s*==\s*['\"]|if\s+user\.role\s*==\s*request\.(json|args|form)"),
        "explanation": "Possible weak authentication or client-trusted role check.",
        "remediation": "Use server-side session identity; never trust client role fields.",
        "impact": "Privilege escalation or weak auth bypass risk.",
    },
    {
        "category": "access_control",
        "severity": Severity.HIGH.value,
        "confidence": 0.6,
        "pattern": re.compile(r"(?i)get_object_or_404\([^\)]*id\s*=\s*request\.|user_id\s*=\s*request\.(args|json|form)"),
        "explanation": "Possible IDOR / missing object-level authorization.",
        "remediation": "Enforce ownership checks server-side for every object access.",
        "impact": "Unauthorized access to other users' resources.",
    },
    {
        "category": "information_disclosure",
        "severity": Severity.LOW.value,
        "confidence": 0.55,
        "pattern": re.compile(r"(?i)traceback\.print_exc\(|DEBUG\s*=\s*True|app\.debug\s*=\s*True"),
        "explanation": "Debug/traceback exposure may leak internals.",
        "remediation": "Disable debug in production; return generic errors.",
        "impact": "Information disclosure aiding attackers.",
    },
]


class WebApplicationSecurityEngine:
    """Defensive analysis for web apps and source — no destructive exploitation required."""

    def __init__(self) -> None:
        pass

    def enrich_finding(self, finding: dict[str, Any]) -> dict[str, Any]:
        cat = finding.get("category") or ""
        out = dict(finding)
        out.setdefault("cwe", _CWE_MAP.get(cat))
        out.setdefault("impact", out.get("impact") or "See severity and explanation.")
        out.setdefault("verification_method", out.get("verification_method") or "static_evidence_recheck")
        out.setdefault("references", out.get("references") or ([out["cwe"]] if out.get("cwe") else []))
        out.setdefault("timestamp", out.get("timestamp") or out.get("provenance", {}).get("ts"))
        # Ensure secrets redacted in evidence
        ev = str(out.get("evidence") or "")
        out["evidence"] = re.sub(
            r"(?i)(password|secret|token|api[_-]?key|authorization)\s*[:=]\s*['\"]?[^'\"\s]+",
            r"\1=[REDACTED]",
            ev,
        )
        return out

    def analyze_source(self, project_path: str) -> dict[str, Any]:
        base = SecureCodeAnalyzer(project_path).analyze()
        findings = [self.enrich_finding(f) for f in (base.get("findings") or [])]
        # Extra rules
        root = Path(project_path)
        if root.exists():
            for path in root.rglob("*"):
                if not path.is_file() or ".pfai" in path.parts or ".git" in path.parts:
                    continue
                if path.suffix.lower() not in {".py", ".js", ".ts", ".tsx", ".jsx", ".html"}:
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                rel = str(path.relative_to(root))
                for rule in _EXTRA_RULES:
                    for i, line in enumerate(text.splitlines(), start=1):
                        if rule["pattern"].search(line):
                            findings.append(
                                self.enrich_finding(
                                    {
                                        "finding_id": new_id("find"),
                                        "category": rule["category"],
                                        "severity": rule["severity"],
                                        "confidence": rule["confidence"],
                                        "affected_component": rel,
                                        "affected_location": f"{rel}:{i}",
                                        "file_path": rel,
                                        "line_hint": i,
                                        "evidence": re.sub(
                                            r"(?i)(password|secret|token)\s*=\s*['\"][^'\"]+['\"]",
                                            r"\1='[REDACTED]'",
                                            line.strip()[:240],
                                        ),
                                        "explanation": rule["explanation"],
                                        "impact": rule["impact"],
                                        "remediation": rule["remediation"],
                                        "verification_status": "open",
                                        "provenance": {"analyzer": "WebApplicationSecurityEngine", "phase": 17},
                                    }
                                )
                            )
        # Dedup
        uniq: dict[str, dict[str, Any]] = {}
        for f in findings:
            key = f"{f.get('category')}:{f.get('file_path')}:{f.get('line_hint')}:{f.get('evidence')}"
            uniq[key] = f
        out = list(uniq.values())
        return {
            "ok": True,
            "finding_count": len(out),
            "findings": out,
            "fabricated": False,
            "engine": "WebApplicationSecurityEngine",
            "note": "Evidence-backed only; no claim of complete security",
        }

    def analyze_headers(self, headers: dict[str, str]) -> dict[str, Any]:
        """Passive header analysis from already-fetched response headers."""
        findings = []
        lower = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
        for h in _HDRS:
            if h not in lower:
                findings.append(
                    self.enrich_finding(
                        {
                            "finding_id": new_id("find"),
                            "category": "missing_security_headers",
                            "severity": Severity.LOW.value,
                            "confidence": 0.85,
                            "affected_component": "http_headers",
                            "affected_location": h,
                            "evidence": f"missing:{h}",
                            "explanation": f"Security header {h} not present.",
                            "impact": "Reduced browser-side hardening.",
                            "remediation": f"Add {h}",
                            "verification_method": "header_recheck",
                        }
                    )
                )
        acao = lower.get("access-control-allow-origin")
        if acao == "*":
            findings.append(
                self.enrich_finding(
                    {
                        "finding_id": new_id("find"),
                        "category": "insecure_cors",
                        "severity": Severity.MEDIUM.value,
                        "confidence": 0.9,
                        "affected_component": "cors",
                        "affected_location": "access-control-allow-origin",
                        "evidence": "Access-Control-Allow-Origin: *",
                        "explanation": "Wildcard CORS origin.",
                        "impact": "Any origin may read responses if credentials misconfigured.",
                        "remediation": "Restrict to explicit trusted origins.",
                        "verification_method": "header_recheck",
                    }
                )
            )
        return {"ok": True, "finding_count": len(findings), "findings": findings, "fabricated": False}

    def analyze_url_config(self, url: str) -> dict[str, Any]:
        """Static URL/TLS configuration hints — no network required."""
        findings = []
        parsed = urlparse(url or "")
        if parsed.scheme == "http":
            findings.append(
                self.enrich_finding(
                    {
                        "finding_id": new_id("find"),
                        "category": "security_misconfiguration",
                        "severity": Severity.MEDIUM.value,
                        "confidence": 0.8,
                        "affected_component": url,
                        "affected_location": "scheme",
                        "evidence": "scheme=http",
                        "explanation": "Cleartext HTTP endpoint configuration.",
                        "impact": "Traffic may be intercepted.",
                        "remediation": "Use HTTPS; enable HSTS.",
                        "verification_method": "config_recheck",
                        "cwe": "CWE-319",
                    }
                )
            )
        return {"ok": True, "finding_count": len(findings), "findings": findings, "fabricated": False}
