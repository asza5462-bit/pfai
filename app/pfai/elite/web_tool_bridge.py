"""PHASE 23 — Connect Web Fabric tools to Tool Fabric with full audit metadata."""
from __future__ import annotations

import time
from typing import Any, Callable

from pfai.authorized_execution import sanitize_args
from pfai.elite.tool_fabric import ToolFabric
from pfai.elite.types import ToolDefinition, new_id
from pfai.elite.web_fabric import WebPolicyGate, WebResearchSession, validate_url_for_fetch, web_config_report
from pfai.elite.web_research_pipeline import WebResearchPipeline
from pfai.interfaces.tools import ToolPermission


def _wrap(
    tool_id: str,
    handler: Callable[..., Any],
    *,
    skill_id: str = "",
) -> Callable[..., Any]:
    def _inner(**kwargs: Any) -> dict[str, Any]:
        started = time.time()
        request_id = str(kwargs.pop("_request_id", "") or new_id("preq"))
        execution_id = new_id("wexec")
        actor = str(kwargs.get("actor") or kwargs.get("_actor") or "")
        approved = bool(kwargs.get("approved") or kwargs.get("_approved"))
        try:
            result = handler(**kwargs)
            ok = bool(result.get("ok")) if isinstance(result, dict) else True
            return sanitize_args(
                {
                    "ok": ok,
                    "result": result,
                    "tool_id": tool_id,
                    "tool_version": "23.0.0",
                    "skill_id": skill_id or None,
                    "request_id": request_id,
                    "execution_id": execution_id,
                    "authorization": {"allowed": True, "approved": approved, "actor": actor[:80]},
                    "budget": {"note": "subject_to_execution_budgets"},
                    "start_time": started,
                    "end_time": time.time(),
                    "result_status": "SUCCESS" if ok else "FAILED",
                    "failure_reason": (result.get("error") if isinstance(result, dict) else None),
                    "provenance": {"layer": "web_tool_bridge"},
                }
            )
        except Exception as exc:  # noqa: BLE001
            return sanitize_args(
                {
                    "ok": False,
                    "error": type(exc).__name__,
                    "tool_id": tool_id,
                    "tool_version": "23.0.0",
                    "request_id": request_id,
                    "execution_id": execution_id,
                    "authorization": {"allowed": True, "approved": approved},
                    "start_time": started,
                    "end_time": time.time(),
                    "result_status": "FAILED",
                    "failure_reason": type(exc).__name__,
                    "provenance": {"layer": "web_tool_bridge"},
                }
            )

    return _inner


def register_web_tools(fabric: ToolFabric, *, activate: bool = True) -> dict[str, Any]:
    """Register web search/fetch/research tools — authorization still via ToolFabric.execute."""

    def web_status(**_kwargs: Any) -> dict[str, Any]:
        return web_config_report()

    def web_search(**kwargs: Any) -> dict[str, Any]:
        query = str(kwargs.get("query") or kwargs.get("input") or "").strip()
        status = web_config_report()
        if status.get("WEB_FABRIC_STATUS") != "READY":
            return {
                "ok": False,
                "WEB_FABRIC_STATUS": status.get("WEB_FABRIC_STATUS") or "NOT_CONFIGURED",
                "error": "web_provider_unavailable",
                "fabricated_results": False,
                "results": [],
            }
        session = WebResearchSession()
        return session.research(
            query,
            limit=int(kwargs.get("limit") or 5),
            approved=bool(kwargs.get("approved")),
            actor=str(kwargs.get("actor") or ""),
        )

    def web_fetch(**kwargs: Any) -> dict[str, Any]:
        url = str(kwargs.get("url") or "").strip()
        gate = WebPolicyGate()
        auth = gate.authorize_url(url, approved=bool(kwargs.get("approved")), actor=str(kwargs.get("actor") or ""))
        if not auth.get("ok"):
            return {"ok": False, "error": auth.get("error"), "ssrf_blocked": True}
        status = web_config_report()
        if status.get("WEB_FABRIC_STATUS") != "READY":
            return {
                "ok": False,
                "WEB_FABRIC_STATUS": status.get("WEB_FABRIC_STATUS") or "NOT_CONFIGURED",
                "error": "web_provider_unavailable",
                "fabricated_results": False,
            }
        check = validate_url_for_fetch(url)
        if not check.get("ok"):
            return {"ok": False, "error": check.get("error"), "ssrf_blocked": True}
        from pfai.elite.web_fabric import WebInformationFabric

        fabric_web = WebInformationFabric()
        return fabric_web.fetch_provider.fetch(url, max_bytes=int(kwargs.get("max_bytes") or 200_000))

    def web_research(**kwargs: Any) -> dict[str, Any]:
        query = str(kwargs.get("query") or kwargs.get("input") or kwargs.get("question") or "").strip()
        return WebResearchPipeline().run(
            query,
            limit=int(kwargs.get("limit") or 5),
            fetch_top=int(kwargs.get("fetch_top") or 1),
            approved=bool(kwargs.get("approved")),
            actor=str(kwargs.get("actor") or ""),
        )

    specs = [
        (
            "web.status",
            "Honest web fabric configuration status",
            web_status,
            ToolPermission.READ.value,
            "low",
        ),
        (
            "web.search",
            "Web search via configured provider (honest NOT_CONFIGURED)",
            web_search,
            ToolPermission.READ.value,
            "medium",
        ),
        (
            "web.fetch",
            "Fetch URL through SSRF/policy gate",
            web_fetch,
            ToolPermission.READ.value,
            "medium",
        ),
        (
            "web.research",
            "Full research pipeline with citations/provenance",
            web_research,
            ToolPermission.READ.value,
            "medium",
        ),
    ]
    registered = []
    skipped = []
    for tool_id, desc, fn, perm, risk in specs:
        definition = ToolDefinition(
            tool_id=tool_id,
            name=tool_id.replace(".", " ").title(),
            description=desc,
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            capabilities=["web", "research", "phase23"],
            permissions_required=perm,
            risk_level=risk,
            execution_environment="local",
            enabled=True,
            health="healthy",
            provenance={"phase": 23, "cannot_self_elevate": True},
        )
        result = fabric.register(definition, _wrap(tool_id, fn), activate=activate)
        if result.get("ok"):
            registered.append(tool_id)
        else:
            skipped.append({"tool_id": tool_id, "error": result.get("error")})
    return {"ok": True, "registered": registered, "skipped": skipped, "count": len(registered)}
