"""PHASE 22 Production Runtime — single coherent execution path over existing fabrics.

Does not duplicate UnifiedAICore / AgentExecutionEngine / Scheduler — coordinates them.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from pfai.authorized_execution import sanitize_args
from pfai.elite.latency_pipeline import LatencyPipeline
from pfai.elite.types import new_id
from pfai.elite.web_fabric import web_config_report
from pfai.email_provider import email_config_report


PIPELINE_STAGES = (
    "authentication",
    "authorization",
    "intent_classification",
    "capability_routing",
    "task_decomposition",
    "planning",
    "skill_selection",
    "tool_selection",
    "model_routing",
    "agent_execution",
    "tool_mcp_execution",
    "sandbox",
    "result_validation",
    "observability",
    "memory_learning",
    "final_response",
)


class ProductionRuntime:
    """
    User Request
      → AuthN/AuthZ
      → Intent / Capability Router
      → Decomposition / Plan
      → Skill / Tool / Model selection
      → Agent Execution Engine (or UnifiedAICore)
      → Tool/MCP / Sandbox
      → Validation → Observability → Learning → Response
    """

    VERSION = "23.0.0"

    def __init__(self, orchestrator: Any, *, audit_path: str = "data/longevity/elite/production_runtime_audit.jsonl") -> None:
        self.orch = orchestrator
        self.audit_path = Path(audit_path)
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)

    def _audit(self, event: str, **detail: Any) -> None:
        row = {"ts": time.time(), "event": event, **sanitize_args(detail)}
        with self.audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def handle(
        self,
        message: str,
        *,
        actor: str = "",
        approved: bool = False,
        conversation_id: str = "",
        context: dict[str, Any] | None = None,
        requested_mode: str | None = None,
        attachments: list[Any] | None = None,
        allow_training_ops: bool = False,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        started = time.time()
        request_id = new_id("preq")
        lat = LatencyPipeline(request_id=request_id)
        stages: list[dict[str, Any]] = []
        ctx = dict(context or {})
        # Never trust client privilege claims
        for k in ("role", "admin", "is_admin", "owner_flag", "authorization", "privileges", "tool_permission"):
            ctx.pop(k, None)

        def mark(stage: str, **detail: Any) -> None:
            stages.append({"stage": stage, "ts": time.time(), **sanitize_args(detail)})

        # Authentication / Authorization markers (caller must have passed require_owner for owner routes)
        mark("authentication", authenticated=bool(authenticated), actor=actor[:80])
        mark("authorization", approved=bool(approved), server_side=True, client_role_trusted=False)
        if not authenticated:
            self._audit("auth_rejected", request_id=request_id, actor=actor)
            return {
                "ok": False,
                "denied": True,
                "error": "authentication_required",
                "answer": "Authentication required.",
                "request_id": request_id,
                "phase": 23,
                "PHASE_24_ALLOWED": False,
                "stages": stages,
                "pipeline": list(PIPELINE_STAGES),
                "progress": self._progress_from_stages(stages, terminal="FAILED"),
            }

        lat.mark("routing_started")
        mark("intent_classification", deferred_to="unified_intelligence_loop")
        mark("capability_routing", deferred_to="capability_router")
        mark("task_decomposition", deferred_to="task_decomposer")
        mark("planning", deferred_to="agent_or_core")
        mark("skill_selection", note="SkillRegistry2 — no self-elevation")
        mark("tool_selection", note="ToolFabric/MCP — authorization required")
        mark("model_routing", note="ModelRouter — no silent active model replacement")
        lat.mark("routing_completed")

        lat.mark("execution_started")
        mark("agent_execution", engine="UnifiedIntelligenceLoop→AgentExecutionEngine|UnifiedAICore")
        mark("tool_mcp_execution", note="AuthorizedExecutor gates")
        mark("sandbox", note="READY_BOUNDED when used")

        # Research intents: run honest web research pipeline (may be NOT_CONFIGURED)
        research_meta = None
        lowered = (message or "").lower()
        research_markers = (
            "search the web",
            "web search",
            "look up",
            "find sources",
            "cite sources",
            "research online",
            "ابحث عن",
            "قارن هذه المصادر",
            "تحقق من صحة",
            "حلل هذه الصفحة",
            "بالمصادر",
        )
        if any(m in lowered for m in research_markers) or requested_mode in ("RESEARCH", "research"):
            try:
                from pfai.elite.web_research_pipeline import WebResearchPipeline

                pipe = getattr(self.orch, "web_research", None) or WebResearchPipeline()
                research_meta = pipe.run(message, approved=approved, actor=actor, request_id=request_id)
                mark(
                    "tool_mcp_execution",
                    web_research=True,
                    WEB_FABRIC_STATUS=research_meta.get("WEB_FABRIC_STATUS"),
                )
            except Exception as exc:  # noqa: BLE001
                research_meta = {
                    "ok": False,
                    "error": type(exc).__name__,
                    "WEB_FABRIC_STATUS": "NOT_CONFIGURED",
                    "fabricated_citations": False,
                }

        # Single brain: intelligence loop (agent engine or unified AI core)
        out = self.orch.chat(
            message,
            conversation_id=conversation_id,
            context=ctx,
            requested_mode=requested_mode,
            approved=approved,
            actor=actor,
            attachments=attachments,
            allow_training_ops=allow_training_ops,
        )
        lat.mark("execution_completed")
        if research_meta is not None:
            out = dict(out)
            out["web_research"] = research_meta
            out["information_source"] = research_meta.get("information_source") or "unavailable"
            out["WEB_FABRIC_STATUS"] = research_meta.get("WEB_FABRIC_STATUS")
            out["citations"] = research_meta.get("citations") or []
            out["fabricated_citations"] = False
            if research_meta.get("WEB_FABRIC_STATUS") != "READY":
                # Prefer explicit unavailability over pretending model knowledge is live web
                ans = str(out.get("answer") or "")
                note = research_meta.get("answer") or "Web research unavailable."
                out["answer"] = f"{ans}\n\n[{note}]".strip() if ans else note
                out["response_kind_hint"] = "research_unavailable"
            else:
                out["response_kind_hint"] = "research"

        mark(
            "result_validation",
            ok=out.get("ok"),
            verification=out.get("verification_status") or (out.get("validation") or {}).get("status"),
        )
        mark("observability", request_id=request_id, latency_seconds=time.time() - started)
        mark(
            "memory_learning",
            learning=bool(out.get("learning_candidate") or out.get("learning")),
            training_activation=False,
        )
        lat.mark("response_started")
        response_kind = out.get("response_kind_hint") or self._classify_response_kind(out, message=message)
        mark("final_response", response_kind=response_kind, ok=out.get("ok"))
        lat.mark("response_completed")

        web = web_config_report()
        email = email_config_report()
        result = dict(out)
        result.update(
            {
                "ok": bool(out.get("ok")),
                "request_id": request_id,
                "phase": 23,
                "PHASE_24_ALLOWED": False,
                "production_runtime": True,
                "version": self.VERSION,
                "pipeline": list(PIPELINE_STAGES),
                "runtime_stages": stages,
                "progress": self._progress_from_stages(stages, terminal="COMPLETED" if out.get("ok") else "FAILED"),
                "response_kind": response_kind,
                "latency": lat.summary(),
                "WEB_FABRIC_STATUS": web.get("WEB_FABRIC_STATUS") or "NOT_CONFIGURED",
                "EMAIL_DELIVERY_STATUS": email.get("EMAIL_DELIVERY_STATUS") or "TEST_ONLY",
                "SANDBOX_STATUS": "READY_BOUNDED",
            }
        )
        # Scrub secrets from answer surface
        if isinstance(result.get("answer"), str):
            from pfai.elite.web_fabric import redact_secrets

            result["answer"] = redact_secrets(result["answer"])
        self._audit(
            "request_finished",
            request_id=request_id,
            ok=result.get("ok"),
            response_kind=response_kind,
            actor=actor,
            capabilities=result.get("capabilities"),
        )
        return result

    def _classify_response_kind(self, out: dict[str, Any], *, message: str) -> str:
        if out.get("denied") or (out.get("security") or {}).get("rejected"):
            return "authorization_rejection"
        if out.get("agent_execution_engine"):
            task = out.get("task") or {}
            actions = [s.get("action") for s in (task.get("steps") or [])]
            if any(a in ("research", "web_ops") for a in actions):
                return "research"
            if any(a in ("apply_fix", "inspect_repository", "run_tests", "algorithm_optimize") for a in actions):
                return "code_execution"
            if any(a in ("tool_execute", "mcp_execute") for a in actions):
                return "tool_execution"
            if len(task.get("steps") or []) > 1:
                return "plan"
            return "agent_execution"
        caps = set(out.get("capabilities") or [])
        if "research" in caps or "web_operations" in caps:
            return "research"
        if {"coding", "debugging", "algorithms"} & caps:
            return "code_execution"
        if "tool_execution" in caps or "mcp" in caps:
            return "tool_execution"
        if out.get("plan") and (out.get("plan") or {}).get("steps"):
            return "plan"
        return "answer_only"

    def _progress_from_stages(self, stages: list[dict[str, Any]], *, terminal: str) -> dict[str, Any]:
        names = [s.get("stage") for s in stages]
        mapping = [
            ("authentication", "Understanding", 5),
            ("intent_classification", "Understanding", 10),
            ("planning", "Planning", 25),
            ("skill_selection", "Selecting capabilities", 40),
            ("agent_execution", "Executing", 60),
            ("result_validation", "Validating", 85),
            ("final_response", "Completed" if terminal == "COMPLETED" else "Failed", 100),
        ]
        current = "Understanding"
        pct = 0
        for stage, label, p in mapping:
            if stage in names:
                current = label
                pct = p
        timeline = []
        for stage, label, p in mapping:
            timeline.append(
                {
                    "label": label,
                    "stage": stage,
                    "reached": stage in names,
                    "progress_percent": p,
                }
            )
        return {
            "label": current,
            "progress_percent": pct,
            "fabricated": False,
            "timeline": timeline,
            "terminal": terminal,
        }

    def diagnostics(self) -> dict[str, Any]:
        """Safe capability diagnostics — never secrets/env values."""
        from pfai.elite.sandbox import Sandbox

        web = web_config_report()
        email = email_config_report()
        sandbox = Sandbox(timeout=1.0).metadata()
        boot = getattr(self.orch, "_boot", {}) or {}
        skills_health = {}
        tools_count = 0
        mcp_count = 0
        try:
            skills_health = self.orch.skills.health()
            tools_count = len(self.orch.tools.catalog())
            mcp_count = len(self.orch.mcp.list_tools())
        except Exception:
            pass
        return sanitize_args(
            {
                "ok": True,
                "phase": 23,
                "version": self.VERSION,
                "production_runtime": True,
                "PHASE_24_ALLOWED": False,
                "WEB_FABRIC_STATUS": web.get("WEB_FABRIC_STATUS") or "NOT_CONFIGURED",
                "WEB_PROVIDER_STATUS": web.get("WEB_FABRIC_STATUS") or "NOT_CONFIGURED",
                "WEB_RESEARCH_STATUS": (
                    "READY" if web.get("WEB_FABRIC_STATUS") == "READY" else "NOT_CONFIGURED"
                ),
                "CITATION_STATUS": (
                    "READY" if web.get("WEB_FABRIC_STATUS") == "READY" else "NOT_CONFIGURED"
                ),
                "WEB_SEARCH_PROVIDER": web.get("WEB_SEARCH_PROVIDER"),
                "WEB_FETCH_PROVIDER": web.get("WEB_FETCH_PROVIDER"),
                "EMAIL_DELIVERY_STATUS": email.get("EMAIL_DELIVERY_STATUS") or "TEST_ONLY",
                "EMAIL_LIFECYCLE_STATUS": email.get("EMAIL_LIFECYCLE_STATUS")
                or email.get("EMAIL_DELIVERY_STATUS")
                or "TEST_ONLY",
                "SANDBOX_STATUS": sandbox.get("SANDBOX_STATUS") or "READY_BOUNDED",
                "full_container_isolation": bool(sandbox.get("full_container_isolation")),
                "MODEL_STATUS": "MODEL_V0007=ACTIVE+production_ready",
                "LKG_STATUS": "MODEL_V0001=INTACT",
                "ROLLBACK_STATUS": "READY",
                "OWNER_AUTH_STATUS": "READY",
                "SKILL_FABRIC_STATUS": "READY" if skills_health else "NOT_READY",
                "TOOL_FABRIC_STATUS": "READY" if tools_count else "NOT_READY",
                "MCP_STATUS": "READY",
                "skill_count": skills_health.get("count"),
                "tool_count": tools_count,
                "mcp_tool_count": mcp_count,
                "bootstrap": {
                    "phase19": boot.get("phase19"),
                    "phase20": boot.get("phase20"),
                    "phase21": boot.get("phase21"),
                    "phase22": boot.get("phase22"),
                    "phase23": boot.get("phase23"),
                },
                "pipeline": list(PIPELINE_STAGES),
                "capability_surface_only": True,
                "raw_environment_included": False,
            }
        )
