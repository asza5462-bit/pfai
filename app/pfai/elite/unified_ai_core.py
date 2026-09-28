"""PHASE 19 Unified AI Core — coherent operating core over existing fabrics.

Preserves authorization, evaluation, rollback, LKG, and honesty about unavailable providers.
Does not replace working components with stubs.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from pfai.authorized_execution import sanitize_args
from pfai.elite.algorithm_intelligence import AlgorithmIntelligence
from pfai.elite.capability_router import CapabilityRouter
from pfai.elite.types import new_id
from pfai.elite.web_fabric import web_config_report


PIPELINE = (
    "user_request",
    "intent_task_analysis",
    "planning",
    "capability_discovery",
    "skill_selection",
    "tool_selection",
    "model_routing",
    "memory_knowledge_retrieval",
    "execution",
    "observation",
    "validation_testing",
    "result",
    "learning_experience_record",
    "evaluation",
    "optional_future_training_data",
)


class UnifiedAICore:
    """
    Receive a user request → determine capabilities → compose skills/tools →
    route model → execute through existing authorized paths → observe/validate →
    learn (gated) → evaluate.

    Never bypasses ActionPermissionGate / TargetRegistry / ScopeEnforcement.
    Never fabricates web results or model availability.
    """

    VERSION = "19.0.0"

    def __init__(
        self,
        orchestrator: Any,
        *,
        audit_path: str = "data/longevity/elite/unified_ai_core_audit.jsonl",
        metrics_path: str = "data/longevity/elite/unified_ai_core_metrics.jsonl",
    ) -> None:
        self.orch = orchestrator
        self.capabilities = CapabilityRouter()
        self.algorithms = AlgorithmIntelligence()
        self.audit_path = Path(audit_path)
        self.metrics_path = Path(metrics_path)
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)

    def _audit(self, event: str, **detail: Any) -> None:
        row = {"ts": time.time(), "event": event, **sanitize_args(detail)}
        with self.audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _metric(self, name: str, value: float, **fields: Any) -> None:
        row = {"ts": time.time(), "metric": name, "value": float(value), **sanitize_args(fields)}
        with self.metrics_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

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
        allow_training_ops: bool = False,
    ) -> dict[str, Any]:
        started = time.time()
        request_id = new_id("uac")
        ctx = dict(context or {})
        stages: list[dict[str, Any]] = []
        metrics: dict[str, float] = {}

        def mark(stage: str, **detail: Any) -> None:
            stages.append({"stage": stage, "ts": time.time(), **sanitize_args(detail)})

        mark("user_request", preview=(message or "")[:200], conversation_id=conversation_id)

        # Privilege escalation / client claims — ignored
        ignored_claims = {
            k: ctx.pop(k)
            for k in list(ctx.keys())
            if k in ("role", "admin", "is_admin", "owner_flag", "authorization", "privileges")
        }
        if ignored_claims:
            mark("authorization", client_claims_ignored=list(ignored_claims.keys()), trusted=False)
            self._audit("client_claims_ignored", request_id=request_id, keys=list(ignored_claims.keys()))

        # Intent / capability discovery
        t0 = time.time()
        cap_route = self.capabilities.route(message, context=ctx)
        metrics["planning_time"] = 0.0  # filled below
        metrics["capability_routing_time"] = time.time() - t0
        capabilities = list(cap_route.get("capabilities") or [])
        mark("intent_task_analysis", capabilities=capabilities, multi=cap_route.get("multi_capability"))
        mark("capability_discovery", capabilities=capabilities, evidence=cap_route.get("evidence"))

        # Planning
        t1 = time.time()
        plan = self._build_plan(capabilities, message=message, context=ctx)
        metrics["planning_time"] = time.time() - t1
        mark("planning", steps=[s["step"] for s in plan["steps"]])

        # Skill selection via existing discovery/composer
        t2 = time.time()
        discovery = self.orch.discovery.discover(message, context=ctx)
        graph = self.orch.composer.compose(message, context=ctx)
        # Enrich graph for multi-capability algorithm/security/coding
        skill_ids = [n.skill_id for n in graph.nodes]
        mark(
            "skill_selection",
            skills=skill_ids,
            graph_id=graph.graph_id,
            intents=discovery.get("intents"),
        )
        metrics["skill_selection_time"] = time.time() - t2

        # Tool selection (catalog filter — no arbitrary execution)
        t3 = time.time()
        tools = self._select_tools(capabilities)
        mark("tool_selection", tools=[t.get("tool_id") for t in tools], count=len(tools))
        metrics["tool_selection_time"] = time.time() - t3

        # Model routing — honest availability
        t4 = time.time()
        model_info = self._route_model(capabilities, message=message, mode=requested_mode)
        metrics["model_latency"] = time.time() - t4
        mark(
            "model_routing",
            ok=model_info.get("ok"),
            available=model_info.get("available"),
            role=model_info.get("role"),
            provider=model_info.get("provider_id") or model_info.get("provider"),
            error=model_info.get("error"),
        )

        # Memory / knowledge retrieval (optional, bounded)
        t5 = time.time()
        memory_hits = self._retrieve_memory(message, capabilities=capabilities)
        metrics["memory_retrieval_time"] = time.time() - t5
        mark("memory_knowledge_retrieval", hits=len(memory_hits), retrieved=bool(memory_hits))

        # Web honesty
        web = web_config_report()
        web_status = web.get("WEB_FABRIC_STATUS") or "NOT_CONFIGURED"
        if "web_operations" in capabilities and web_status != "READY":
            mark("web_operations", status=web_status, fabricated=False, note="NOT_CONFIGURED_no_fake_results")

        # Unauthorized external testing / offensive — preserve security.rejected for audit
        if self._looks_like_unrestricted_external_test(message) and not (
            ctx.get("target_id") and approved
        ):
            self._audit("blocked_unrestricted_external_test", request_id=request_id, actor=actor)
            # Still run elite for consistent offensive rejection metadata when phrasing matches
            elite_block = None
            try:
                elite_block = self.orch.handle(
                    message,
                    conversation_id=conversation_id,
                    context=ctx,
                    requested_mode=requested_mode,
                    approved=approved,
                    actor=actor,
                    attachments=attachments,
                )
            except Exception:
                elite_block = None
            out = {
                "ok": False,
                "denied": True,
                "error": "unrestricted_external_testing_forbidden",
                "answer": (elite_block or {}).get("answer")
                or "Rejected: external security testing requires a registered authorized target and owner approval.",
                "security": (elite_block or {}).get("security")
                or {"rejected": True, "offensive_blocked": True},
                "request_id": request_id,
                "capabilities": capabilities,
                "phase": 19,
                "WEB_FABRIC_STATUS": web_status,
                "stages": stages,
                "pipeline": list(PIPELINE),
                "PHASE_20_ALLOWED": False,
                "skills_used": [],
                "model_routing": {
                    k: model_info.get(k)
                    for k in ("ok", "available", "role", "provider_id", "error")
                    if k in model_info
                },
            }
            self._finalize_metrics(metrics, started, request_id=request_id, ok=False)
            return out

        # Execution — specialize by capability set, then fall through to elite handle
        t6 = time.time()
        execution: dict[str, Any] = {"ok": True, "parts": []}
        try:
            execution = self._execute(
                message,
                capabilities=capabilities,
                plan=plan,
                context=ctx,
                approved=approved,
                actor=actor,
                conversation_id=conversation_id,
                requested_mode=requested_mode,
                attachments=attachments,
                allow_training_ops=allow_training_ops,
                model_info=model_info,
                memory_hits=memory_hits,
            )
        except Exception as exc:  # noqa: BLE001
            # Failure recovery
            recovery = self.orch.recovery.next_action(
                error=type(exc).__name__,
                attempt=1,
            )
            execution = {
                "ok": False,
                "error": type(exc).__name__,
                "detail": str(exc)[:300],
                "recovery": recovery,
                "parts": [],
            }
            mark("failure_recovery", **sanitize_args(recovery if isinstance(recovery, dict) else {"action": recovery}))
        metrics["execution_time"] = time.time() - t6
        metrics["tool_latency"] = float((execution.get("tool_latency") or 0.0))
        mark(
            "execution",
            ok=execution.get("ok"),
            parts=[p.get("capability") for p in execution.get("parts") or []],
            error=execution.get("error"),
        )
        mark("observation", summary=str(execution.get("summary") or "")[:240])

        # Validation
        t7 = time.time()
        validation = self.orch.self_check.verify(
            result=execution.get("result") or execution,
            execution_ok=bool(execution.get("ok")),
            test_failed=int((execution.get("test_failed") or 0)),
            schema_required_keys=["ok"],
        )
        metrics["validation_time"] = time.time() - t7
        mark("validation_testing", status=validation.get("status"), ok=validation.get("ok"))

        # Compose answer
        answer = execution.get("answer") or execution.get("summary") or ""
        if not answer and execution.get("parts"):
            answer = self._compose_answer(execution["parts"])

        # Learning / experience (gated — no auto-trust)
        learn = self._record_learning(
            message=message,
            execution=execution,
            validation=validation,
            capabilities=capabilities,
            actor=actor,
        )
        mark(
            "learning_experience_record",
            recorded=bool(learn.get("recorded")),
            eligibility=learn.get("eligibility"),
        )
        mark("evaluation", status=validation.get("status"), learn=learn.get("eligibility"))
        mark(
            "optional_future_training_data",
            auto_started=False,
            candidate=bool(learn.get("recorded")),
            note="Training requires separate quality gates; cannot alter authz; LKG preserved",
        )

        metrics["total_task_time"] = time.time() - started
        self._finalize_metrics(metrics, started, request_id=request_id, ok=bool(execution.get("ok")))

        audit_record = {
            "request_id": request_id,
            "task_type": capabilities[0] if capabilities else "unknown",
            "selected_capabilities": capabilities,
            "selected_skills": skill_ids,
            "selected_tools": [t.get("tool_id") for t in tools],
            "selected_model": {
                "role": model_info.get("role"),
                "provider": model_info.get("provider_id") or model_info.get("provider"),
                "available": model_info.get("available"),
            },
            "execution_stages": [s.get("stage") for s in stages],
            "validation_status": validation.get("status"),
            "final_result_status": "SUCCESS" if execution.get("ok") and validation.get("ok") else "FAILED",
            "learning_evaluation_status": learn.get("eligibility"),
        }
        self._audit("unified_execution", **audit_record)

        elite_out = execution.get("elite") or {}
        phase15_payload = elite_out.get("phase15") or elite_out.get("phase14")
        if not phase15_payload and execution.get("security"):
            phase15_payload = {
                "ok": True,
                "finding_count": (execution.get("security") or {}).get("finding_count"),
                "findings": (execution.get("security") or {}).get("findings"),
                "intent": "security_review",
            }
        if not phase15_payload and execution.get("algorithm"):
            phase15_payload = {"ok": execution.get("ok"), "algorithm": True}
        out = {
            "ok": bool(execution.get("ok")) and bool(validation.get("ok")),
            "answer": answer,
            "request_id": request_id,
            "capabilities": capabilities,
            "capability_routing": cap_route,
            "plan": plan,
            "skills_used": skill_ids or list(capabilities),
            "tools_selected": [t.get("tool_id") for t in tools],
            "tools_used": [t.get("tool_id") for t in tools],
            "models_used": [model_info.get("provider_id") or model_info.get("role")] if model_info.get("available") else [],
            "model_routing": {
                k: model_info.get(k)
                for k in ("ok", "available", "role", "provider_id", "provider", "error", "fallback", "capabilities")
                if k in model_info or model_info.get(k) is not None
            },
            "memory_hits": memory_hits[:5],
            "execution": {
                "parts": execution.get("parts"),
                "summary": execution.get("summary"),
                "algorithm": execution.get("algorithm"),
                "security": execution.get("security"),
                "coding": execution.get("coding"),
            },
            "validation": validation,
            "learning_candidate": learn,
            "stages": stages,
            "pipeline": list(PIPELINE),
            "metrics": metrics,
            "audit_record": sanitize_args(audit_record),
            "WEB_FABRIC_STATUS": web_status,
            "execution_status": validation.get("status"),
            "verification_status": validation.get("status"),
            "phase": 19,
            "phase18": elite_out.get("phase18"),
            "phase15": phase15_payload,
            "phase14": elite_out.get("phase14") or phase15_payload,
            "PHASE_20_ALLOWED": False,
            "latency_seconds": metrics["total_task_time"],
            "unified_ai_core": True,
            "version": self.VERSION,
            "finding_count": (execution.get("security") or {}).get("finding_count")
            or (phase15_payload or {}).get("finding_count"),
        }
        # Preserve security rejection from elite if present
        if (elite_out.get("security") or {}).get("rejected"):
            out["ok"] = False
            out["security"] = elite_out.get("security")
            out["answer"] = elite_out.get("answer") or out["answer"]
        return out

    def _build_plan(self, capabilities: list[str], *, message: str, context: dict[str, Any]) -> dict[str, Any]:
        steps = []
        for cap in capabilities:
            steps.append({"step": cap, "action": f"execute_capability:{cap}"})
        if "evaluation" not in capabilities:
            steps.append({"step": "evaluation", "action": "self_check"})
        return {"ok": True, "steps": steps, "message_preview": (message or "")[:120]}

    def _select_tools(self, capabilities: list[str]) -> list[dict[str, Any]]:
        catalog = []
        try:
            catalog = list(self.orch.tools.catalog() or [])
        except Exception:
            return []
        wanted: set[str] = set()
        if "security_analysis" in capabilities:
            wanted.update({"security_code_review", "security_scope_check", "security_secret_scan"})
        if "web_operations" in capabilities:
            wanted.update({"web_fetch", "web_search"})
        if "coding" in capabilities or "testing" in capabilities:
            wanted.update({"sandbox_exec", "pytest_runner"})
        if "mcp" in capabilities:
            try:
                for t in self.orch.mcp.list_tools() or []:
                    wanted.add(str(t.get("tool_id") or t.get("name") or ""))
            except Exception:
                pass
        selected = []
        for row in catalog:
            tid = row.get("tool_id") or row.get("id")
            if tid in wanted or (not wanted and len(selected) < 3):
                selected.append(row)
            if len(selected) >= 8:
                break
        return selected

    def _route_model(self, capabilities: list[str], *, message: str, mode: str | None) -> dict[str, Any]:
        router = getattr(self.orch, "model_router", None)
        if router is None:
            return {
                "ok": False,
                "available": False,
                "error": "model_router_not_configured",
                "note": "No model claimed available without runtime confirmation",
            }
        hints = self.capabilities.model_capability_hints(capabilities)
        try:
            if hasattr(router, "select_by_capabilities"):
                info = router.select_by_capabilities(hints, prefer_local=True)
            elif hasattr(router, "route_for_task"):
                info = router.route_for_task(message, mode=mode)
            else:
                info = {"ok": False, "available": False, "error": "router_missing_select"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "available": False, "error": type(exc).__name__}
        # Never expose live provider object in audit
        if isinstance(info, dict) and "provider" in info and not isinstance(info.get("provider"), (str, type(None))):
            info = dict(info)
            info["provider"] = type(info["provider"]).__name__
        return info

    def _retrieve_memory(self, message: str, *, capabilities: list[str]) -> list[dict[str, Any]]:
        if not any(c in capabilities for c in ("memory_retrieval", "knowledge_retrieval", "coding", "algorithms")):
            # Still allow light retrieval for complex multi-cap tasks
            if len(capabilities) < 3:
                return []
        hits: list[dict[str, Any]] = []
        # Skill learning bridge as lightweight prior experience (not unverified chat trust)
        try:
            bridge = getattr(self.orch, "learning", None)
            if bridge and hasattr(bridge, "eligible_training_candidates"):
                for row in list(bridge.eligible_training_candidates())[:3]:
                    hits.append(
                        {
                            "source": "skill_learning_bridge",
                            "verified": True,
                            "preview": str(row)[:160],
                        }
                    )
        except Exception:
            pass
        # Experience bridge if present
        try:
            exp = getattr(self.orch, "experience_bridge", None)
            if exp and hasattr(exp, "recent"):
                for row in list(exp.recent(limit=3) or []):
                    hits.append({"source": "experience_bridge", "verified": True, "preview": str(row)[:160]})
        except Exception:
            pass
        return hits

    def _looks_like_unrestricted_external_test(self, message: str) -> bool:
        t = (message or "").lower()
        return any(
            w in t
            for w in (
                "scan the internet",
                "hack into",
                " pentest ",
                "attack example.com",
                "unrestricted scan",
                "scan all websites",
            )
        )

    def _execute(
        self,
        message: str,
        *,
        capabilities: list[str],
        plan: dict[str, Any],
        context: dict[str, Any],
        approved: bool,
        actor: str,
        conversation_id: str,
        requested_mode: str | None,
        attachments: list[Any] | None,
        allow_training_ops: bool,
        model_info: dict[str, Any],
        memory_hits: list[dict[str, Any]],
    ) -> dict[str, Any]:
        parts: list[dict[str, Any]] = []
        algorithm = None
        security = None
        coding = None
        elite = None
        test_failed = 0
        tool_latency = 0.0

        # Algorithm capability — real structured pipeline
        if "algorithms" in capabilities:
            code = str(context.get("code") or "")
            implement = any(
                w in (message or "").lower()
                for w in ("implement", "optimized", "optimize", "write", "code")
            )
            algorithm = self.algorithms.full_pipeline(message, code=code, implement=implement)
            parts.append(
                {
                    "capability": "algorithms",
                    "ok": algorithm.get("ok"),
                    "result": {
                        "analysis": algorithm.get("analysis"),
                        "test_result": algorithm.get("test_result"),
                        "explanation": algorithm.get("explanation"),
                    },
                }
            )
            if algorithm.get("test_result") and algorithm["test_result"].get("ran"):
                if not algorithm["test_result"].get("ok"):
                    test_failed += 1

        # Coding / debugging via CodingAgentBridge or elite when project_path present
        if any(c in capabilities for c in ("coding", "debugging", "architecture", "testing")) and context.get(
            "project_path"
        ):
            from pfai.engineering.coding_agent_bridge import CodingAgentBridge

            bridge = CodingAgentBridge(registry=None)
            path = str(context["project_path"])
            insp = bridge.inspect_repository(path, actor=actor, approved=approved)
            coding = {"inspection": insp}
            if "debugging" in capabilities or "testing" in capabilities:
                # Search for common failure markers
                search = bridge.search_code(path, context.get("query") or "TODO", actor=actor, approved=approved)
                coding["search"] = {"ok": search.get("ok"), "hits": len(search.get("hits") or [])}
            parts.append({"capability": "coding", "ok": bool(insp.get("ok")), "result": coding})

        # Security analysis on local path
        if "security_analysis" in capabilities and context.get("project_path"):
            from pfai.engineering.phase18_security import Phase18SecurityAnalysis

            security = Phase18SecurityAnalysis().analyze(str(context["project_path"]))
            parts.append(
                {
                    "capability": "security_analysis",
                    "ok": security.get("ok"),
                    "result": {
                        "finding_count": security.get("finding_count"),
                        "claim_100_percent_secure": False,
                    },
                }
            )

        # Remediation when requested
        if "remediation" in capabilities and context.get("project_path"):
            from pfai.engineering.remediation_engine import RemediationEngine

            rem = RemediationEngine(allow_auto_safe_fixes=False).run(
                str(context["project_path"]),
                approved=approved,
                actor=actor,
                target_id=str(context.get("target_id") or ""),
                auto_apply=bool(context.get("auto_apply")),
                owner_approved_sensitive=bool(context.get("owner_approved_sensitive")),
            )
            parts.append({"capability": "remediation", "ok": rem.get("ok") and not rem.get("denied"), "result": {"pipeline": rem.get("pipeline"), "denied": rem.get("denied")}})

        # Application engineering
        if "application_engineering" in capabilities:
            from pfai.engineering.phase18_chat import Phase18ChatFabric

            eng = Phase18ChatFabric(root=str(Path(getattr(self.orch, "root", Path("data/longevity/elite")) / "appeng")))
            built = eng.handle(message, approved=approved, actor=actor, context=context)
            parts.append(
                {
                    "capability": "application_engineering",
                    "ok": bool(built.get("complete") or built.get("ok")),
                    "result": {"intent": built.get("intent"), "complete": built.get("complete")},
                }
            )
            elite = {"phase18": built, "phase15": built, "phase14": built}

        # Model training meta — never auto; only acknowledge
        if "model_training" in capabilities and not allow_training_ops:
            parts.append(
                {
                    "capability": "model_training",
                    "ok": True,
                    "result": {
                        "auto_started": False,
                        "note": "Training ops require allow_training_ops + owner gates; LKG preserved",
                    },
                }
            )

        # Always run elite orchestrator for remaining composition / chat surface
        # unless we already fully handled a pure algorithm+security+coding E2E with project
        needs_elite = elite is None and (
            not parts
            or any(
                c in capabilities
                for c in (
                    "reasoning",
                    "planning",
                    "research",
                    "document_processing",
                    "data_analysis",
                    "mathematics",
                    "tool_execution",
                    "mcp",
                    "learning",
                    "evaluation",
                    "web_operations",
                    "application_engineering",
                    "security_analysis",
                    "coding",
                    "debugging",
                )
            )
        )
        # For rich multi-cap algorithm E2E without project_path, elite still useful for answer framing
        if needs_elite and "application_engineering" not in capabilities:
            t_tool = time.time()
            elite = self.orch.handle(
                message,
                conversation_id=conversation_id,
                context=context,
                requested_mode=requested_mode,
                approved=approved,
                actor=actor,
                attachments=attachments,
            )
            tool_latency = time.time() - t_tool
            parts.append(
                {
                    "capability": "elite_orchestrator",
                    "ok": elite.get("ok"),
                    "result": {
                        "execution_status": elite.get("execution_status"),
                        "skills_used": elite.get("skills_used"),
                    },
                }
            )

        ok = all(bool(p.get("ok")) for p in parts) if parts else bool(elite and elite.get("ok"))
        if elite and (elite.get("security") or {}).get("rejected"):
            ok = False

        summary = self._compose_answer(parts)
        if algorithm and algorithm.get("explanation"):
            summary = (algorithm["explanation"] + "\n" + summary).strip()
        if elite and elite.get("answer") and "algorithms" not in capabilities:
            summary = elite.get("answer") or summary

        return {
            "ok": ok,
            "parts": parts,
            "algorithm": algorithm,
            "security": security,
            "coding": coding,
            "elite": elite,
            "summary": summary,
            "answer": summary,
            "result": {"ok": ok, "parts": parts},
            "test_failed": test_failed,
            "tool_latency": tool_latency,
            "model_info": model_info,
            "memory_hits": memory_hits,
        }

    def _compose_answer(self, parts: list[dict[str, Any]]) -> str:
        lines = []
        for p in parts:
            cap = p.get("capability")
            res = p.get("result") or {}
            if cap == "algorithms":
                lines.append(str((res.get("explanation") or res))[:500])
            elif cap == "security_analysis":
                lines.append(f"Security findings: {res.get('finding_count', 0)} (not 100% secure claim).")
            elif cap == "coding":
                lines.append(f"Repository inspection ok={((res.get('inspection') or {}).get('ok'))}.")
            elif cap == "application_engineering":
                lines.append(f"Application engineering intent={res.get('intent')} complete={res.get('complete')}.")
            elif cap == "elite_orchestrator":
                lines.append(f"Orchestrator status={res.get('execution_status')}.")
            else:
                lines.append(f"{cap}: ok={p.get('ok')}")
        return "\n".join(lines) if lines else "Completed unified AI core pipeline."

    def _record_learning(
        self,
        *,
        message: str,
        execution: dict[str, Any],
        validation: dict[str, Any],
        capabilities: list[str],
        actor: str,
    ) -> dict[str, Any]:
        # Only record when validation passed — never auto-trust failures as knowledge
        if not (execution.get("ok") and validation.get("ok")):
            return {"recorded": False, "eligibility": "rejected_unverified", "reason": "validation_or_execution_failed"}
        recorded = False
        eligibility = "candidate"
        try:
            bridge = getattr(self.orch, "learning", None)
            if bridge and hasattr(bridge, "record_experience"):
                bridge.record_experience(
                    task=message[:300],
                    skills_used=list(capabilities),
                    models_used=[],
                    tools_used=[],
                    result_status="SUCCESS",
                    verification_status=str(validation.get("status") or "SUCCESS"),
                    meta={"phase": 19, "verified": True},
                )
                recorded = True
                eligibility = "accepted_verified"
        except Exception as exc:  # noqa: BLE001
            return {"recorded": False, "eligibility": "error", "error": type(exc).__name__}
        # Experience bridge — coding pass only when tests ran ok
        try:
            exp = getattr(self.orch, "experience_bridge", None)
            algo = execution.get("algorithm") or {}
            tr = (algo.get("test_result") or {}) if isinstance(algo, dict) else {}
            if exp and tr.get("ran") and tr.get("ok") and hasattr(exp, "record_code_test_pass"):
                exp.record_code_test_pass(
                    instruction=message[:300],
                    code=str(((algo.get("implementation") or {}) or {}).get("code") or "")[:2000],
                    source_id="phase19_algorithm",
                    provenance={"phase": 19, "verified": True},
                )
                recorded = True
                eligibility = "accepted_verified"
        except Exception:
            pass
        return {
            "recorded": recorded,
            "eligibility": eligibility,
            "cannot_modify_authorization": True,
            "unverified_not_trusted": True,
        }

    def _finalize_metrics(self, metrics: dict[str, float], started: float, *, request_id: str, ok: bool) -> None:
        metrics.setdefault("total_task_time", time.time() - started)
        for k, v in metrics.items():
            self._metric(k, float(v), request_id=request_id, ok=ok)
