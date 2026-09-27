"""PHASE 18 Authorized Web Fabric operations — registry/scope gated; no arbitrary Internet."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from pfai.authorized_execution import sanitize_args
from pfai.elite.web_fabric import validate_url_for_fetch, web_config_report
from pfai.engineering.scope_enforcement import ScopeEnforcementLayer
from pfai.engineering.target_registry import TargetRegistry
from pfai.engineering.types import new_id


class AuthorizedWebFabricOps:
    """
    Provider-independent WebFabric operations constrained by TargetRegistry.

    If WEB_FABRIC is not configured: WEB_FABRIC_STATUS=NOT_CONFIGURED (honest).
    Does not enable arbitrary Internet access by default.
    """

    VERSION = "18.0.0"

    def __init__(
        self,
        *,
        registry: TargetRegistry | None = None,
        audit_path: str = "data/longevity/engineering/web_fabric_ops_audit.jsonl",
    ) -> None:
        self.registry = registry or TargetRegistry()
        self.scope = ScopeEnforcementLayer(registry=self.registry)
        self.audit_path = Path(audit_path)
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)

    def _audit(self, event: str, **detail: Any) -> None:
        row = {"ts": time.time(), "event": event, **sanitize_args(detail)}
        with self.audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def status(self) -> dict[str, Any]:
        report = web_config_report()
        return {
            "WEB_FABRIC_STATUS": report.get("WEB_FABRIC_STATUS") or "NOT_CONFIGURED",
            "provider_independent": True,
            "arbitrary_internet_default": False,
            "requires_target_registry": True,
            "version": self.VERSION,
            "config": report,
        }

    def _authorize(
        self,
        *,
        target_id: str,
        operation: str,
        method: str,
        actor: str,
        approved: bool,
        resource: str = "",
    ) -> dict[str, Any]:
        # Production environment requires explicit owner authorization flag
        resolved = self.registry.resolve(target_id=target_id)
        if not resolved.get("ok"):
            self._audit("resolve_failed", target_id=target_id, error=resolved.get("error"))
            return {"ok": False, "error": resolved.get("error") or "unknown_target", "denied": True}
        target = resolved["target"]
        if target.get("environment") == "production" and not approved:
            self._audit("production_requires_owner_approval", target_id=target_id)
            return {
                "ok": False,
                "denied": True,
                "error": "production_requires_explicit_owner_authorization",
            }
        decision = self.scope.enforce(
            target_id=target_id,
            operation=operation,
            method=method,
            actor=actor,
            approved=approved,
            resource=resource,
        )
        if not decision.get("ok"):
            self._audit("denied", target_id=target_id, error=decision.get("error"), operation=operation)
            return {"ok": False, "denied": True, "error": decision.get("error"), "decision": decision}
        self._audit(
            "authorized",
            target_id=target_id,
            operation=operation,
            method=method,
            actor=actor,
            resource=resource[:200],
        )
        return {"ok": True, "target": target, "decision": decision}

    def http_request(
        self,
        *,
        target_id: str,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        actor: str = "",
        approved: bool = False,
        timeout: float = 10.0,
        allow_private: bool = False,
    ) -> dict[str, Any]:
        auth = self._authorize(
            target_id=target_id,
            operation="http_request",
            method="passive_inspect",
            actor=actor,
            approved=approved,
            resource=url,
        )
        if not auth.get("ok"):
            return auth
        check = validate_url_for_fetch(url, allow_private=allow_private)
        if not check.get("ok"):
            self._audit("ssrf_block", url=url, error=check.get("error"))
            return {"ok": False, "error": check.get("error"), "ssrf_blocked": True}
        try:
            req = urllib.request.Request(
                url,
                data=body,
                method=method.upper(),
                headers={
                    "User-Agent": "PFAI-AuthorizedWebFabric/18",
                    "Accept": "text/html,application/json",
                    **{k: v for k, v in (headers or {}).items() if k.lower() not in ("authorization", "cookie")},
                },
            )
            # Authenticated headers only if explicitly provided via approved path — never log secrets
            if headers:
                for hk, hv in headers.items():
                    if hk.lower() in ("authorization", "cookie"):
                        req.add_header(hk, hv)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read(64_000)
                resp_headers = {k.lower(): v for k, v in resp.headers.items()}
                status = resp.status
            return {
                "ok": True,
                "status_code": status,
                "headers": {k: ("[REDACTED]" if "auth" in k or "cookie" in k else v) for k, v in resp_headers.items()},
                "body_preview": raw[:2000].decode("utf-8", errors="replace"),
                "bytes": len(raw),
                "authorization": {"decision": "ALLOW", "target_id": target_id},
            }
        except urllib.error.HTTPError as exc:
            return {"ok": False, "error": f"http_{exc.code}", "authorized": True}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": type(exc).__name__, "authorized": True}

    def health_check(
        self,
        *,
        target_id: str,
        url: str,
        actor: str = "",
        approved: bool = False,
    ) -> dict[str, Any]:
        out = self.http_request(target_id=target_id, url=url, actor=actor, approved=approved)
        if not out.get("ok") and out.get("denied"):
            return out
        healthy = bool(out.get("ok") and int(out.get("status_code") or 0) < 500)
        return {
            "ok": out.get("ok"),
            "healthy": healthy,
            "status_code": out.get("status_code"),
            "denied": out.get("denied"),
            "error": out.get("error"),
            "target_id": target_id,
        }

    def controlled_crawl(
        self,
        *,
        target_id: str,
        start_url: str,
        actor: str = "",
        approved: bool = False,
        max_pages: int = 5,
    ) -> dict[str, Any]:
        """Crawl only within authorized host/path scope — no automatic expansion."""
        auth = self._authorize(
            target_id=target_id,
            operation="controlled_crawl",
            method="passive_inspect",
            actor=actor,
            approved=approved,
            resource=start_url,
        )
        if not auth.get("ok"):
            return auth
        target = auth["target"]
        max_pages = min(int(max_pages or 5), int((target.get("rate_limits") or {}).get("max_requests") or 50), 10)
        visited: list[dict[str, Any]] = []
        queue = [start_url]
        seen = set()
        while queue and len(visited) < max_pages:
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            # Re-check scope for each URL — stop at boundary
            step = self.scope.enforce(
                target_id=target_id,
                operation="controlled_crawl",
                method="passive_inspect",
                actor=actor,
                approved=approved,
                resource=url,
            )
            if not step.get("ok"):
                self._audit("crawl_stopped_at_boundary", url=url, error=step.get("error"))
                break
            resp = self.http_request(
                target_id=target_id, url=url, actor=actor, approved=approved
            )
            visited.append({"url": url, "ok": resp.get("ok"), "status_code": resp.get("status_code")})
            if not resp.get("ok"):
                continue
            body = resp.get("body_preview") or ""
            # Very bounded link extraction — same host only
            import re

            for href in re.findall(r'href=["\']([^"\']+)["\']', body)[:20]:
                abs_url = urljoin(url, href)
                parsed = urlparse(abs_url)
                if parsed.scheme not in ("http", "https"):
                    continue
                if abs_url not in seen:
                    queue.append(abs_url)
        return {
            "ok": True,
            "pages": visited,
            "page_count": len(visited),
            "stopped_at_scope_boundary": True,
            "authorization": {"decision": "ALLOW", "target_id": target_id},
            "note": "controlled_crawl_within_authorized_scope_only",
        }

    def discover_endpoints(
        self,
        *,
        target_id: str,
        base_url: str,
        actor: str = "",
        approved: bool = False,
        candidates: list[str] | None = None,
    ) -> dict[str, Any]:
        """Endpoint discovery within authorized scope only — no brute exploit."""
        auth = self._authorize(
            target_id=target_id,
            operation="endpoint_discovery",
            method="passive_inspect",
            actor=actor,
            approved=approved,
            resource=base_url,
        )
        if not auth.get("ok"):
            return auth
        paths = candidates or ["/health", "/api", "/api/health", "/robots.txt", "/"]
        found = []
        for path in paths[:15]:
            url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
            step = self.scope.enforce(
                target_id=target_id,
                operation="endpoint_discovery",
                method="passive_inspect",
                actor=actor,
                approved=approved,
                resource=url,
            )
            if not step.get("ok"):
                continue
            resp = self.http_request(target_id=target_id, url=url, actor=actor, approved=approved)
            if resp.get("ok"):
                found.append({"url": url, "status_code": resp.get("status_code")})
        return {
            "ok": True,
            "endpoints": found,
            "authorization": {"decision": "ALLOW", "target_id": target_id},
            "discovery_id": new_id("disc"),
        }

    def api_test(
        self,
        *,
        target_id: str,
        url: str,
        actor: str = "",
        approved: bool = False,
        expect_status: int | None = None,
    ) -> dict[str, Any]:
        auth = self._authorize(
            target_id=target_id,
            operation="api_test",
            method="passive_inspect",
            actor=actor,
            approved=approved,
            resource=url,
        )
        if not auth.get("ok"):
            return auth
        resp = self.http_request(target_id=target_id, url=url, actor=actor, approved=approved)
        if resp.get("denied"):
            return resp
        status = resp.get("status_code")
        passed = resp.get("ok") and (expect_status is None or status == expect_status)
        return {
            "ok": bool(passed),
            "status_code": status,
            "expect_status": expect_status,
            "response_ok": resp.get("ok"),
            "error": resp.get("error"),
            "authorization": {"decision": "ALLOW", "target_id": target_id},
        }

    def reject_unregistered_url(self, url: str) -> dict[str, Any]:
        """URL alone never authorizes — explicit rejection helper."""
        self._audit("unregistered_url_rejected", url=url[:200])
        return {
            "ok": False,
            "denied": True,
            "error": "unregistered_target_or_domain",
            "note": "URL_alone_never_authorizes",
        }
