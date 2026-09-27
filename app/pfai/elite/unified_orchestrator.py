"""PHASE 13 Unified Elite Orchestrator — intent → plan → skills → model → tools → verify → learn."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from pfai.authorized_execution import AuthorizedExecutor, PermissionGate, sanitize_args
from pfai.elite.composer import SkillComposer
from pfai.elite.discovery import SkillDiscoveryEngine
from pfai.elite.elite_library import register_elite_skills
from pfai.elite.mcp_adapter import MCPAdapter
from pfai.elite.sandbox import Sandbox
from pfai.elite.self_check_engine import FailureRecovery, SelfCheckEngine
from pfai.elite.skill_learning import SkillLearningBridge
from pfai.elite.skill_registry_v2 import SkillRegistry2
from pfai.elite.tool_fabric import ToolFabric
from pfai.elite.types import OrchestratorMode, new_id
from pfai.elite.web_fabric import WEB_PROVIDER_UNAVAILABLE, WebInformationFabric
from pfai.model_router import ModelRouter


class EliteOrchestrator:
    """Coordinates discovery → composition → model/tool routing → verify → learn."""

    def __init__(
        self,
        root: str = "data/longevity/elite",
        *,
        executor: AuthorizedExecutor | None = None,
        model_router: ModelRouter | None = None,
        tool_router: Any = None,
        experience_bridge: Any = None,
        bootstrap_skills: bool = True,
        web_fabric: WebInformationFabric | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.executor = executor or AuthorizedExecutor(PermissionGate())
        self.model_router = model_router
        self.experience_bridge = experience_bridge
        self.web = web_fabric or WebInformationFabric()
        self.skills = SkillRegistry2(
            path=str(self.root / "skill_registry_v2.sqlite3"),
            executor=self.executor,
            history_path=str(self.root / "skill_promotion_history.jsonl"),
        )
        self.discovery = SkillDiscoveryEngine(self.skills)
        self.composer = SkillComposer(self.skills, self.discovery)
        self.tools = ToolFabric(
            path=str(self.root / "tool_fabric.sqlite3"),
            executor=self.executor,
            tool_router=tool_router,
        )
        self.mcp = MCPAdapter(
            path=str(self.root / "mcp_adapter.json"),
            executor=self.executor,
            fabric=self.tools,
        )
        self.self_check = SelfCheckEngine()
        self.recovery = FailureRecovery(max_retries=2)
        self.learning = SkillLearningBridge(path=str(self.root / "skill_learning.jsonl"))
        self.audit_path = self.root / "elite_audit.jsonl"
        self._lock = threading.RLock()
        self._boot = {"skills": None, "tools": None}
        if bootstrap_skills:
            self._boot["skills"] = register_elite_skills(self.skills, activate=True)
            self._boot["tools"] = self.tools.bootstrap_safe_tools()

    def _audit(self, event: str, **detail: Any) -> None:
        row = {"ts": time.time(), "event": event, "detail": sanitize_args(detail)}
        with self._lock:
            with self.audit_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _detect_mode(self, message: str, requested: str | None) -> str:
        if requested:
            return requested.upper()
        intents = self.discovery.infer_intents(message)
        mapping = {
            "code": OrchestratorMode.CODE.value,
            "research": OrchestratorMode.RESEARCH.value,
            "web": OrchestratorMode.RESEARCH.value,
            "data": OrchestratorMode.DATA.value,
            "document": OrchestratorMode.DOCUMENT.value,
            "tool": OrchestratorMode.TOOL.value,
            "reason": OrchestratorMode.REASON.value,
            "write": OrchestratorMode.CHAT.value,
            "ai": OrchestratorMode.PLAN.value,
        }
        return mapping.get(intents[0], OrchestratorMode.CHAT.value)

    def _analyze_intent(self, message: str, requested_mode: str | None) -> dict[str, Any]:
        intents = self.discovery.infer_intents(message)
        mode = self._detect_mode(message, requested_mode)
        return {
            "intents": intents,
            "mode": mode,
            "user_selected_model": False,
            "user_selected_skill": False,
            "user_selected_tool": False,
        }

    def _route_model(self, mode: str, message: str) -> dict[str, Any]:
        if self.model_router is None:
            return {"ok": False, "available": False, "error": "model_router_unavailable", "role": None}
        # Capability-driven routing (Phase 13)
        if hasattr(self.model_router, "route_for_task"):
            routed = self.model_router.route_for_task(message, mode=mode)
            if not routed.get("available"):
                return {
                    "ok": False,
                    "available": False,
                    "error": routed.get("error") or "provider_unavailable",
                    "role": routed.get("role"),
                    "audit": routed.get("audit"),
                    "capabilities_requested": routed.get("capabilities_requested"),
                }
            provider = routed.get("provider")
            role = routed.get("role") or "default"
            name = routed.get("provider_id") or type(provider).__name__
        else:
            role = "default"
            m = mode.upper()
            if m == "CODE":
                role = "coding"
            elif m in ("REASON", "RESEARCH", "PLAN"):
                role = "reasoning"
            try:
                provider = self.model_router.resolve(role)
            except Exception as exc:
                return {"ok": False, "available": False, "error": type(exc).__name__, "role": role}
            name = type(provider).__name__

        if provider is None:
            return {"ok": False, "available": False, "error": "provider_missing", "role": role}
        available = True
        reply = None
        try:
            if hasattr(provider, "generate"):
                out = provider.generate(message[:500])
                reply = out if isinstance(out, str) else str(out)
            elif hasattr(provider, "complete"):
                out = provider.complete(message[:500])
                reply = out if isinstance(out, str) else str(out)
            else:
                available = False
                reply = None
        except Exception as exc:
            return {
                "ok": False,
                "available": False,
                "error": str(exc),
                "role": role,
                "provider": name,
                "audit": {"exception": type(exc).__name__},
            }
        return {
            "ok": available,
            "available": available,
            "role": role,
            "provider": name,
            "reply": reply,
            "privileges_granted": False,
        }

    def handle(
        self,
        message: str,
        *,
        conversation_id: str = "",
        context: dict[str, Any] | None = None,
        requested_mode: str | None = None,
        approved: bool = False,
        actor: str = "",
        attachments: list[Any] | None = None,
    ) -> dict[str, Any]:
        started = time.time()
        ctx = dict(context or {})
        intent = self._analyze_intent(message, requested_mode)
        mode = intent["mode"]
        timeline: list[dict[str, Any]] = [{"event": "intent_analysis", "intent": intent}]
        execution_id = new_id("exec")

        lowered = (message or "").lower()
        if any(
            p in lowered
            for p in (
                "ignore security",
                "make me owner",
                "disable authorization",
                "reveal secrets",
                "bypass owner",
            )
        ):
            self._audit("security_reject", message=message[:200], actor=actor)
            return {
                "ok": False,
                "answer": "Rejected: privilege escalation / secret disclosure requests are not honored.",
                "execution_status": "FAILED",
                "verification_status": "FAILED",
                "skills_used": [],
                "models_used": [],
                "tools_used": [],
                "execution_id": execution_id,
                "mode": mode,
                "security": {"rejected": True},
                "phase": 13,
            }

        # Task planner (lightweight)
        plan = {
            "steps": [
                "skill_discovery",
                "skill_composition",
                "model_routing",
                "tool_mcp_sandbox",
                "verification",
                "learning",
            ],
            "mode": mode,
        }
        timeline.append({"event": "task_planner", "plan": plan})

        discovery = self.discovery.discover(message, context=ctx)
        timeline.append(
            {"event": "skill_discovery", "candidates": [c["skill_id"] for c in discovery.get("candidates") or []]}
        )
        graph = self.composer.compose(message, context=ctx)
        timeline.append(
            {"event": "skill_composition", "graph_id": graph.graph_id, "nodes": [n.skill_id for n in graph.nodes]}
        )

        model_info = self._route_model(mode, message)
        timeline.append({"event": "model_routing", "model": {k: model_info.get(k) for k in ("ok", "available", "role", "provider", "error")}})

        # Web fabric when research/web intent
        web_result = None
        if mode == OrchestratorMode.RESEARCH.value or "web" in intent["intents"]:
            web_result = self.web.research(message, limit=5, fetch_top=0)
            timeline.append(
                {
                    "event": "web_fabric",
                    "status": web_result.status,
                    "ok": web_result.ok,
                    "error": web_result.error or None,
                }
            )

        initial_args: dict[str, Any] = {
            "task": message,
            "goal": message,
            "question": message,
            "prompt": message,
            "spec": message,
            "topic": message,
            "text": message,
            "document": message,
            "problem": message,
            "query": message,
            "catalog": self.tools.catalog(),
            "tree": ctx.get("files") or [],
            "rows": ctx.get("rows") or [],
            "attachments": attachments or [],
            "citations": [c.to_dict() for c in (web_result.citations if web_result else [])],
        }

        tools_used: list[str] = []
        tool_result = None
        if mode in (OrchestratorMode.TOOL.value, OrchestratorMode.CODE.value):
            sel = self.tools.select(
                "calc" if "calc" in lowered or any(ch in message for ch in "+-*/") else "echo"
            )
            selected = (sel.get("selected") or [None])[0]
            if selected:
                tid = selected.get("tool_id") or selected.get("name")
                if tid:
                    targs = {"text": message, "expression": message}
                    tool_result = self.tools.execute(tid, targs, approved=approved, actor=actor)
                    tools_used.append(tid)
                    timeline.append({"event": "tool_execution", "tool_id": tid, "ok": tool_result.get("ok")})
                    if not tool_result.get("ok") and tool_result.get("needs_approval"):
                        return {
                            "ok": False,
                            "answer": "Tool requires owner approval.",
                            "execution_status": "NEEDS_APPROVAL",
                            "verification_status": "UNVERIFIED",
                            "skills_used": [],
                            "models_used": [model_info.get("role")] if model_info.get("role") else [],
                            "tools_used": tools_used,
                            "execution_id": execution_id,
                            "mode": mode,
                            "tool_result": tool_result,
                            "phase": 13,
                        }
                    if not tool_result.get("ok"):
                        rec = self.recovery.next_action(
                            error=str(tool_result.get("error")), attempt=1, alternatives=["echo_text"]
                        )
                        timeline.append({"event": "failure_recovery", "recovery": rec})
                        if rec.get("action") == "alternative":
                            tool_result = self.tools.execute(
                                rec["alternative"], {"text": message}, approved=approved, actor=actor
                            )
                            tools_used.append(rec["alternative"])

        compose_out = self.composer.execute(
            graph,
            initial_args=initial_args,
            approved=approved,
            actor=actor,
            stop_on_failure=False,
        )
        timeline.append({"event": "skill_execution", "status": compose_out.get("status")})

        sandbox_result = None
        sandbox_meta = None
        if mode == OrchestratorMode.CODE.value:
            code = None
            for step in compose_out.get("trace") or []:
                out = step.get("output") or {}
                if isinstance(out, dict) and out.get("code"):
                    code = out["code"]
                    break
            if code:
                sb = Sandbox(timeout=3.0)
                sandbox_meta = sb.metadata()
                try:
                    sb.write_text("solution.py", code)
                    sandbox_result = sb.run(["python3", "-m", "py_compile", "solution.py"])
                    timeline.append({"event": "sandbox", "ok": sandbox_result.get("ok")})
                finally:
                    sb.cleanup()

        verification = self.self_check.verify(
            result=compose_out.get("final"),
            execution_ok=bool(compose_out.get("ok")),
            requirements=[],
            test_failed=0 if not sandbox_result or sandbox_result.get("ok") else 1,
        )
        timeline.append({"event": "verification", "status": verification.get("status")})

        skills_used = [n.skill_id for n in graph.nodes]
        models_used = [model_info["role"]] if model_info.get("role") else []

        answer_parts = []
        if web_result is not None:
            if web_result.ok:
                answer_parts.append(web_result.summary)
            else:
                answer_parts.append(f"WEB_STATUS={WEB_PROVIDER_UNAVAILABLE}")
        if model_info.get("reply"):
            answer_parts.append(str(model_info["reply"])[:1500])
        final = compose_out.get("final")
        if isinstance(final, dict):
            if final.get("summary"):
                answer_parts.append(str(final["summary"]))
            elif final.get("synthesis"):
                answer_parts.append(json.dumps(final["synthesis"], ensure_ascii=False)[:1500])
            elif final.get("code"):
                answer_parts.append(final["code"])
            elif final.get("answer_outline"):
                answer_parts.append(" | ".join(map(str, final["answer_outline"])))
            elif final.get("status") == WEB_PROVIDER_UNAVAILABLE or final.get("error") == WEB_PROVIDER_UNAVAILABLE:
                answer_parts.append(f"WEB_STATUS={WEB_PROVIDER_UNAVAILABLE}")
            else:
                answer_parts.append(json.dumps(final, ensure_ascii=False)[:1500])
        if tool_result and tool_result.get("ok"):
            answer_parts.append(f"tool:{json.dumps(tool_result.get('result'), ensure_ascii=False)[:500]}")
        answer = "\n\n".join(p for p in answer_parts if p) or "Completed skill composition with verification."

        learn = self.learning.record_experience(
            task=message,
            skills_used=skills_used,
            models_used=models_used,
            tools_used=tools_used,
            result_status=compose_out.get("status") or "UNVERIFIED",
            verification_status=verification.get("status") or "UNVERIFIED",
            meta={"mode": mode, "execution_id": execution_id, "conversation_id": conversation_id},
            skill_id=skills_used[0] if skills_used else "",
            model_version=str(model_info.get("provider") or ""),
        )
        timeline.append({"event": "learning", "learning_event_id": learn.get("learning_event_id")})
        timeline.append({"event": "evaluation", "status": verification.get("status")})

        status = verification.get("status") or compose_out.get("status") or "UNVERIFIED"
        citations = None
        if web_result and web_result.citations:
            citations = [c.to_dict() for c in web_result.citations]
        elif isinstance(final, dict):
            citations = final.get("citations")

        out = {
            "ok": status in ("SUCCESS", "PARTIAL_SUCCESS"),
            "answer": answer,
            "execution_status": status,
            "verification_status": verification.get("status"),
            "skills_used": skills_used,
            "models_used": models_used,
            "tools_used": tools_used,
            "citations": citations,
            "claim_kinds": [c.get("claim_kind") for c in (web_result.claims if web_result else [])][:10]
            if web_result
            else None,
            "learning_event_id": learn.get("learning_event_id"),
            "execution_id": execution_id,
            "conversation_id": conversation_id or execution_id,
            "mode": mode,
            "intent": intent,
            "discovery": {"intents": discovery.get("intents"), "candidates": discovery.get("candidates")[:5]},
            "composition": compose_out.get("graph"),
            "composition_plan": compose_out.get("plan"),
            "verification": verification,
            "model_routing": {
                k: model_info.get(k)
                for k in ("ok", "available", "role", "provider", "error", "privileges_granted")
            },
            "web": {
                "status": web_result.status if web_result else None,
                "ok": web_result.ok if web_result else None,
                "error": web_result.error if web_result else None,
                "provider": web_result.provider if web_result else None,
            }
            if web_result is not None
            else self.web.status(),
            "tool_result": tool_result,
            "sandbox": sandbox_result,
            "sandbox_metadata": sandbox_meta,
            "timeline": timeline,
            "latency_seconds": time.time() - started,
            "phase": 13,
            "optional_future_training": True,
        }
        self._audit("elite_handle", execution_id=execution_id, mode=mode, status=status, actor=actor)
        return out

    def status(self) -> dict[str, Any]:
        tool_status = self.tools.status_registry()
        return {
            "phase": 13,
            "skills": self.skills.health(),
            "tools": {"count": len(self.tools.catalog()), **{k: tool_status.get(k) for k in ("REAL_TOOL_COUNT", "MOCK_TOOL_COUNT")}},
            "mcp_tools": len(self.mcp.list_tools()),
            "bootstrap": self._boot,
            "learning_events": len(self.learning.eligible_training_candidates())
            if self.learning.path.exists()
            else 0,
            "model_router": bool(self.model_router),
            "web": self.web.status(),
            "sandbox": Sandbox(timeout=1.0).metadata(),
            "EMAIL_NOTE": "see /platform/email/status",
        }

    def export_learning_to_training(self, limit: int = 20) -> dict[str, Any]:
        return self.learning.export_to_experience_bridge(self.experience_bridge, limit=limit)
