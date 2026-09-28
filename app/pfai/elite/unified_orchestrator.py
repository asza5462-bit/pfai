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
        from pfai.engineering.skill_metrics import SkillEvaluationLedger

        self.skill_metrics = SkillEvaluationLedger(path=str(self.root / "skill_evaluations.jsonl"))
        self.audit_path = self.root / "elite_audit.jsonl"
        self._lock = threading.RLock()
        self._boot = {
            "skills": None,
            "tools": None,
            "phase14": None,
            "phase15": None,
            "phase16": True,
            "phase17": None,
            "phase18": None,
            "phase19": None,
            "phase20": None,
            "phase21": None,
            "phase22": None,
            "phase23": None,
            "web_tools": None,
        }
        if bootstrap_skills:
            from pfai.engineering.phase14_skills import register_phase14_skills
            from pfai.engineering.phase15_skills import register_phase15_skills
            from pfai.engineering.phase17_skills import register_phase17_skills
            from pfai.engineering.phase18_skills import register_phase18_skills
            from pfai.elite.phase19_skills import register_phase19_skills
            from pfai.elite.phase20_skills import register_phase20_skills
            from pfai.elite.phase21_skills import register_phase21_skills
            from pfai.elite.phase22_skills import register_phase22_skills
            from pfai.elite.phase23_skills import register_phase23_skills
            from pfai.elite.web_tool_bridge import register_web_tools

            self._boot["skills"] = register_elite_skills(self.skills, activate=True)
            self._boot["phase14"] = register_phase14_skills(self.skills, activate=True)
            self._boot["phase15"] = register_phase15_skills(self.skills, activate=True)
            self._boot["phase17"] = register_phase17_skills(self.skills, activate=True)
            self._boot["phase18"] = register_phase18_skills(self.skills, activate=True)
            self._boot["phase19"] = register_phase19_skills(self.skills, activate=True)
            self._boot["phase20"] = register_phase20_skills(self.skills, activate=True)
            self._boot["phase21"] = register_phase21_skills(self.skills, activate=True)
            self._boot["phase22"] = register_phase22_skills(self.skills, activate=True)
            self._boot["phase23"] = register_phase23_skills(self.skills, activate=True)
            self._boot["tools"] = self.tools.bootstrap_safe_tools()
            self._boot["security_tools"] = self.tools.bootstrap_security_tools()
            self._boot["web_tools"] = register_web_tools(self.tools, activate=True)
        from pfai.elite.unified_intelligence_loop import UnifiedIntelligenceLoop
        from pfai.elite.performance_engine import PerformanceReliabilityEngine
        from pfai.elite.production_runtime import ProductionRuntime
        from pfai.elite.mcp_registry import MCPServerRegistry

        self.intelligence = UnifiedIntelligenceLoop(self)
        self.performance = PerformanceReliabilityEngine(
            self,
            root=str(Path(self.root) / "phase21"),
            max_workers=4,
        )
        self.production = ProductionRuntime(
            self,
            audit_path=str(Path(self.root) / "production_runtime_audit.jsonl"),
        )
        self.mcp_registry = MCPServerRegistry(
            path=str(Path(self.root) / "mcp_servers.json"),
            adapter=self.mcp,
        )
        self.web_research = None
        try:
            from pfai.elite.web_research_pipeline import WebResearchPipeline

            self.web_research = WebResearchPipeline(
                audit_path=str(Path(self.root) / "web_research_audit.jsonl"),
            )
        except Exception:
            self.web_research = None

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
            "engineering": OrchestratorMode.CODE.value,
            "security": OrchestratorMode.TOOL.value,
            "algorithms": OrchestratorMode.CODE.value,
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
                "phase": 17,
            }

        # Reject unauthorized offensive / third-party attack language
        if any(
            p in lowered
            for p in (
                "exploit this website",
                "hack into",
                "steal credentials",
                "ransomware",
                "persist malware",
                "evade detection",
                "attack example.com",
            )
        ):
            self._audit("offensive_reject", message=message[:200], actor=actor)
            return {
                "ok": False,
                "answer": "Rejected: unauthorized/offensive exploitation requests are not supported. Use authorized defensive analysis on owned targets only.",
                "execution_status": "FAILED",
                "verification_status": "FAILED",
                "skills_used": [],
                "models_used": [],
                "tools_used": [],
                "execution_id": execution_id,
                "mode": mode,
                "security": {"rejected": True, "offensive_blocked": True},
                "phase": 17,
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

        # Phase 14/15/18 specialized engineering / authorized defense paths
        phase14_result = None
        phase15_result = None
        phase18_result = None
        if any(
            w in lowered or w in message
            for w in (
                "build me a website",
                "build a website",
                "create a full-stack",
                "full-stack application",
                "build an api",
                "create an application",
                "build a web application",
                "build me an app",
                "ابن",
                "ابنِ",
                "ابني",
                "موقعا",
            )
        ):
            from pfai.engineering.phase18_chat import Phase18ChatFabric

            phase18_result = Phase18ChatFabric(root=str(self.root / "appeng")).handle(
                message, approved=approved, actor=actor, context=ctx
            )
            phase15_result = phase18_result
            phase14_result = phase18_result
            timeline.append(
                {
                    "event": "phase18_application_engineering",
                    "ok": phase18_result.get("ok"),
                    "complete": phase18_result.get("complete"),
                    "intent": phase18_result.get("intent"),
                }
            )
            self.skill_metrics.record(
                skill_id="application_engineering_build",
                success=bool(phase18_result.get("complete") or phase18_result.get("ok")),
                validation_ok=bool(phase18_result.get("complete")),
                security_findings=int(
                    ((phase18_result.get("artifact") or {}).get("security") or {}).get("finding_count") or 0
                ),
                user_approved=approved or None,
                duration_seconds=time.time() - started,
            )
        elif any(
            w in lowered or w in message
            for w in (
                "افحص",
                "أصلح",
                "اصلح",
                "طوّر",
                "طور",
                "check my site",
                "inspect my website",
            )
        ):
            from pfai.engineering.phase18_chat import Phase18ChatFabric

            phase18_result = Phase18ChatFabric(root=str(self.root / "appeng")).handle(
                message, approved=approved, actor=actor, context=ctx
            )
            phase15_result = phase18_result
            phase14_result = phase18_result
            timeline.append(
                {
                    "event": "phase18_chat_fabric",
                    "ok": phase18_result.get("ok"),
                    "denied": phase18_result.get("denied"),
                    "intent": phase18_result.get("intent"),
                }
            )
        elif any(
            w in lowered
            for w in (
                "security development lifecycle",
                "build this application securely",
                "secure sdlc",
            )
        ):
            from pfai.engineering.security_ops import SecurityDevelopmentLifecycle

            sdlc = SecurityDevelopmentLifecycle()
            phase15_result = sdlc.run_for_project(
                message,
                project_path=str(ctx.get("project_path") or ""),
                approved=approved,
                actor=actor,
                target_id=str(ctx.get("target_id") or ""),
                auto_remediate=bool(ctx.get("auto_remediate") or ctx.get("auto_apply")),
            )
            phase14_result = phase15_result
            timeline.append(
                {
                    "event": "security_sdlc",
                    "ok": phase15_result.get("ok"),
                    "security_ready": phase15_result.get("security_ready"),
                }
            )
        elif any(
            w in lowered
            for w in (
                "review this project for security",
                "security problems",
                "find security weaknesses",
                "secure code analysis",
                "vulnerability",
                "check my application for security",
                "fix the vulnerabilities",
                "remediat",
                "review this application for security",
                "analyze this api",
                "generate a safe remediation",
                "apply the approved remediation",
                "retest the application",
                "create a security regression test",
            )
        ):
            from pfai.engineering.unified_coding_workflow import UnifiedCodingWorkflow

            ucw = UnifiedCodingWorkflow(
                root=str(self.root / "coding_workflow"),
                executor=self.executor,
                experience_bridge=self.experience_bridge,
                skill_metrics=self.skill_metrics,
            )
            phase15_result = ucw.handle(
                message,
                project_path=str(ctx.get("project_path") or ctx.get("path") or ""),
                approved=approved,
                actor=actor,
                declaration=str(ctx.get("declaration") or ""),
                scope=str(ctx.get("scope") or ""),
                allow_external=bool(ctx.get("allow_external")),
                auto_apply=bool(ctx.get("auto_apply")),
                context=ctx,
            )
            phase14_result = phase15_result
            timeline.append(
                {
                    "event": "security_workflow",
                    "ok": phase15_result.get("ok"),
                    "denied": phase15_result.get("denied"),
                    "intent": phase15_result.get("intent"),
                }
            )
            self.skill_metrics.record(
                skill_id="secure_code_analysis",
                success=bool(phase15_result.get("ok")),
                security_findings=int(
                    phase15_result.get("finding_count") or len(phase15_result.get("findings") or [])
                ),
                duration_seconds=time.time() - started,
            )
        elif any(
            w in lowered
            for w in ("inspect project", "analyze architecture", "repository inspection", "project structure")
        ):
            from pfai.engineering.unified_coding_workflow import UnifiedCodingWorkflow

            ucw = UnifiedCodingWorkflow(root=str(self.root / "coding_workflow"), executor=self.executor)
            phase15_result = ucw.handle(
                message,
                project_path=str(ctx.get("project_path") or ctx.get("path") or ""),
                approved=approved,
                actor=actor,
                context=ctx,
            )
            timeline.append({"event": "project_inspection", "ok": phase15_result.get("ok")})

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
        if phase14_result is not None:
            if phase14_result.get("complete") is False and phase14_result.get("artifact"):
                answer = (phase14_result.get("artifact") or {}).get("report") or answer
            elif phase14_result.get("denied"):
                answer = f"Authorized testing denied: {phase14_result.get('error')}"
            elif phase14_result.get("findings") is not None:
                answer = f"Security analysis findings: {phase14_result.get('finding_count', len(phase14_result.get('findings') or []))}"
            elif phase14_result.get("fixed_count") is not None:
                answer = (
                    f"Remediation complete: fixed={phase14_result.get('fixed_count')} "
                    f"unverified={phase14_result.get('unverified_count')} "
                    f"rolled_back={phase14_result.get('rolled_back')}"
                )
            elif phase14_result.get("artifact"):
                art = phase14_result["artifact"]
                answer = art.get("report") or f"Built project at {art.get('root')} complete={phase14_result.get('complete')}"
            elif phase14_result.get("architecture"):
                answer = f"Project inspection architecture={phase14_result.get('architecture')}"


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
            "phase": 18 if phase18_result is not None else 17,
            "phase14": phase14_result,
            "phase15": phase15_result,
            "phase18": phase18_result,
            "optional_future_training": True,
            "PHASE_19_ALLOWED": False,
        }
        self._audit("elite_handle", execution_id=execution_id, mode=mode, status=status, actor=actor)
        return out

    def status(self) -> dict[str, Any]:
        tool_status = self.tools.status_registry()
        from pfai.engineering.phase14_skills import phase14_status
        from pfai.engineering.phase15_gates import phase15_status
        from pfai.engineering.phase16_gates import phase16_status
        from pfai.engineering.phase17_gates import phase17_status
        from pfai.engineering.phase18_gates import phase18_status
        from pfai.elite.phase19_gates import phase19_status
        from pfai.elite.phase20_gates import phase20_status
        from pfai.elite.phase21_gates import phase21_status
        from pfai.elite.phase22_gates import phase22_status
        from pfai.elite.phase23_gates import phase23_status

        p14 = phase14_status()
        p15 = phase15_status()
        p16 = phase16_status()
        p17 = phase17_status()
        p18 = phase18_status()
        p19 = phase19_status()
        p20 = phase20_status()
        p21 = phase21_status()
        p22 = phase22_status()
        p23 = phase23_status()
        return {
            "phase": 23,
            "skills": self.skills.health(),
            "tools": {
                "count": len(self.tools.catalog()),
                **{k: tool_status.get(k) for k in ("REAL_TOOL_COUNT", "MOCK_TOOL_COUNT")},
            },
            "mcp_tools": len(self.mcp.list_tools()),
            "bootstrap": self._boot,
            "learning_events": len(self.learning.eligible_training_candidates())
            if self.learning.path.exists()
            else 0,
            "model_router": bool(self.model_router),
            "web": self.web.status(),
            "sandbox": Sandbox(timeout=1.0).metadata(),
            "EMAIL_NOTE": "Email OTP REMOVED; see /platform/email/status",
            "phase14": p14,
            "phase15": p15,
            "phase16": p16,
            "phase17": p17,
            "phase18": p18,
            "phase19": p19,
            "phase20": p20,
            "phase21": p21,
            "phase22": p22,
            "phase23": p23,
            "scheduler": self.performance.scheduler_status() if getattr(self, "performance", None) else None,
            "runtime": self.production.diagnostics() if getattr(self, "production", None) else None,
            "mcp_registry": self.mcp_registry.health() if getattr(self, "mcp_registry", None) else None,
            "PHASE_14_ALLOWED": bool(p14.get("PHASE_14_ALLOWED")),
            "PHASE_15_ALLOWED": bool(p15.get("PHASE_15_ALLOWED")),
            "PHASE_16_ALLOWED": bool(p16.get("PHASE_16_ALLOWED")),
            "PHASE_17_ALLOWED": bool(p17.get("PHASE_17_ALLOWED")),
            "PHASE_18_ALLOWED": bool(p18.get("PHASE_18_ALLOWED")),
            "PHASE_19_ALLOWED": bool(p19.get("PHASE_19_ALLOWED")),
            "PHASE_20_ALLOWED": bool(p20.get("PHASE_20_ALLOWED")),
            "PHASE_21_ALLOWED": bool(p21.get("PHASE_21_ALLOWED")),
            "PHASE_22_ALLOWED": bool(p22.get("PHASE_22_ALLOWED")),
            "PHASE_23_ALLOWED": bool(p23.get("PHASE_23_ALLOWED")),
            "PHASE_24_ALLOWED": False,
            "skill_metrics": self.skill_metrics.summary(),
            "unified_intelligence_loop": True,
            "unified_ai_core": True,
            "agent_execution_engine": True,
            "performance_reliability_engine": True,
            "production_runtime": True,
            "web_research_pipeline": True,
        }

    def chat(
        self,
        message: str,
        *,
        conversation_id: str = "",
        context: dict[str, Any] | None = None,
        requested_mode: str | None = None,
        approved: bool = False,
        actor: str = "",
        attachments: list[Any] | None = None,
        allow_training_ops: bool = False,
    ) -> dict[str, Any]:
        """Primary command surface — routes through UnifiedIntelligenceLoop."""
        return self.intelligence.run(
            message,
            conversation_id=conversation_id,
            context=context,
            requested_mode=requested_mode,
            approved=approved,
            actor=actor,
            attachments=attachments,
            allow_training_ops=allow_training_ops,
        )

    def export_learning_to_training(self, limit: int = 20) -> dict[str, Any]:
        return self.learning.export_to_experience_bridge(self.experience_bridge, limit=limit)
