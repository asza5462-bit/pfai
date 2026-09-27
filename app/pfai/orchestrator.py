"""PFAI Orchestrator — central planning/execution layer (PHASE 4).

Coordinates Command Chat, Coding AI, Planner, Skills, Tools, LTM, Knowledge,
Evaluation, Learning, Self-check and bounded Self-heal.
Does not bypass Owner Gate. Never mutates model weights or core security/architecture.
"""
from __future__ import annotations

import re
from typing import Any

from pfai.interfaces.learning import LearningSource
from pfai.interfaces.memory import MemoryKind, MemoryRecord
from pfai.interfaces.orchestrator import OrchestratorProtocol
from pfai.interfaces.types import OrchestratorRequest, OrchestratorResult, TimelineStatus
from pfai.model_router import ModelRouter
from pfai.skills.registry import SkillRegistry

__all__ = [
    "OrchestratorProtocol",
    "OrchestratorRequest",
    "OrchestratorResult",
    "TimelineStatus",
    "Orchestrator",
]

PHASE = 4


class Orchestrator:
    def __init__(
        self,
        *,
        model_router: ModelRouter | None = None,
        command_agent: Any = None,
        coding_agent: Any = None,
        skills: SkillRegistry | None = None,
        ltm: Any = None,
        knowledge_search: Any = None,
        learning: Any = None,
        evaluation: Any = None,
        self_check: Any = None,
        self_heal: Any = None,
        planner: Any = None,
        wired: bool = True,
    ) -> None:
        self.model_router = model_router
        self.command_agent = command_agent
        self.coding_agent = coding_agent
        self.skills = skills or SkillRegistry()
        self.ltm = ltm
        self.knowledge_search = knowledge_search
        self.learning = learning
        self.evaluation = evaluation
        self.self_check = self_check
        self.self_heal = self_heal
        self.planner = planner
        self._wired = wired and any(
            x is not None
            for x in (command_agent, coding_agent, learning, self_check, model_router, planner)
        )

    def handle(self, request: OrchestratorRequest) -> OrchestratorResult:
        if not self._wired:
            raise NotImplementedError("Orchestrator is not wired — provide subsystem adapters")

        timeline: list[TimelineStatus] = [
            TimelineStatus("thinking", "orchestrator received goal"),
            TimelineStatus("planning", f"mode={request.mode}"),
        ]
        goal = (request.goal or "").strip()
        if not goal:
            return OrchestratorResult(ok=False, error="goal is required", timeline=timeline)

        mode = (request.mode or "general").strip().lower()
        try:
            if mode in ("self_check", "diagnostics"):
                return self._run_self_check(request, timeline)
            if mode in ("self_heal", "heal"):
                return self._run_self_heal(request, timeline)
            if mode in ("learn", "learning", "feedback"):
                return self._run_learning(request, timeline)
            if mode in ("evaluate", "eval"):
                return self._run_eval(request, timeline)
            if mode in ("memory", "ltm"):
                return self._run_memory(request, timeline)
            if mode in ("knowledge", "rag"):
                return self._run_knowledge(request, timeline)
            if mode in ("skill", "skills"):
                return self._run_skill(request, timeline)
            if mode in ("plan", "planner"):
                return self._run_plan(request, timeline)
            if mode.startswith("coding") or _looks_coding(goal):
                return self._run_coding(request, timeline)
            if mode in ("ops", "general", "chat", ""):
                return self._run_command(request, timeline)
            return self._run_command(request, timeline)
        except Exception as exc:
            timeline.append(TimelineStatus("failed", str(exc)))
            return OrchestratorResult(ok=False, error=str(exc), timeline=timeline, reply=str(exc))

    def status(self) -> dict[str, Any]:
        return {
            "phase": PHASE,
            "wired": self._wired,
            "has_command": self.command_agent is not None,
            "has_coding": self.coding_agent is not None,
            "has_planner": self.planner is not None,
            "has_skills": len(self.skills.list_skills()) if self.skills else 0,
            "has_ltm": self.ltm is not None,
            "has_learning": self.learning is not None,
            "has_evaluation": self.evaluation is not None,
            "has_self_check": self.self_check is not None,
            "has_self_heal": self.self_heal is not None,
            "model_router": self.model_router.describe() if self.model_router else None,
            "anthropic_required": False,
            "allows_weight_mutation": False,
            "learning_training_readiness": (
                self.learning.training_readiness()
                if self.learning and hasattr(self.learning, "training_readiness")
                else {"weight_training_allowed_now": False}
            ),
        }

    def _run_plan(self, request: OrchestratorRequest, timeline: list[TimelineStatus]) -> OrchestratorResult:
        if self.planner is None:
            return OrchestratorResult(ok=False, error="planner not connected", timeline=timeline)
        ctx = request.context or {}
        approved = bool(ctx.get("approved"))
        actions = ctx.get("actions")
        plan = self.planner.plan(request.goal, actions=actions)
        timeline.append(TimelineStatus("planning", f"steps={len(plan.steps)}"))
        if ctx.get("plan_only"):
            return OrchestratorResult(
                ok=True,
                reply="plan created",
                timeline=timeline + [TimelineStatus("completed", "plan_only")],
                meta={"plan_id": plan.plan_id, "steps": [{"id": s.id, "action": s.action} for s in plan.steps]},
            )
        ran = self.planner.run(plan, approved=approved, actor=request.user_id or "", verify=bool(ctx.get("verify", True)))
        for s in ran.steps:
            timeline.append(TimelineStatus(s.status, s.action, meta={"error": s.error, "result": s.result}))
        needs = ran.status == "waiting_for_approval"
        return OrchestratorResult(
            ok=ran.status in ("verified", "completed", "unverified") and not needs,
            needs_approval=needs,
            approval_id=ran.plan_id if needs else None,
            reply=f"plan {ran.status}",
            timeline=timeline + [TimelineStatus("completed" if ran.status.startswith("verif") or ran.status == "completed" else ran.status, ran.plan_id)],
            meta={
                "plan_id": ran.plan_id,
                "status": ran.status,
                "verification": ran.verification,
                "steps": [{"id": s.id, "action": s.action, "status": s.status, "error": s.error} for s in ran.steps],
            },
            error=None if ran.status != "failed" else "plan failed",
        )

    def _run_command(self, request: OrchestratorRequest, timeline: list[TimelineStatus]) -> OrchestratorResult:
        if self.command_agent is None:
            return OrchestratorResult(ok=False, error="command_agent not connected", timeline=timeline)
        timeline.append(TimelineStatus("calling_tool", "command_agent"))
        owner = (request.context or {}).get("owner") or request.user_id or "owner"
        result = self.command_agent.handle(
            request.goal,
            owner=owner,
            conversation_id=request.session_id or None,
            language=request.locale,
        )
        for step in result.get("timeline") or []:
            timeline.append(TimelineStatus(step.get("status", "executing"), step.get("detail", ""), meta=step))
        return OrchestratorResult(
            ok=bool(result.get("ok", True)),
            reply=result.get("reply") or "",
            timeline=timeline,
            tool_calls=result.get("tool_calls") or [],
            needs_approval=bool(result.get("needs_approval") or result.get("status") == "waiting_for_approval"),
            approval_id=result.get("pending_id") or result.get("approval_id"),
            meta={"provider": result.get("provider"), "conversation_id": result.get("conversation_id"), "via": "command_agent"},
            error=result.get("error"),
        )

    def _run_coding(self, request: OrchestratorRequest, timeline: list[TimelineStatus]) -> OrchestratorResult:
        if self.coding_agent is None:
            return self._run_command(request, timeline)
        timeline.append(TimelineStatus("calling_tool", "coding_agent"))
        owner = (request.context or {}).get("owner") or request.user_id or "owner"
        result = self.coding_agent.handle(request.goal, owner=owner)
        for step in result.get("timeline") or []:
            timeline.append(TimelineStatus(step.get("status", "teaching"), step.get("detail", ""), meta=step))
        return OrchestratorResult(
            ok=bool(result.get("ok", True)),
            reply=result.get("reply") or "",
            timeline=timeline,
            meta={"via": "coding_agent", "intent": result.get("intent"), "coding": result},
            error=result.get("error"),
        )

    def _run_skill(self, request: OrchestratorRequest, timeline: list[TimelineStatus]) -> OrchestratorResult:
        name = (request.context or {}).get("skill") or ""
        args = (request.context or {}).get("args") or {}
        approved = bool((request.context or {}).get("approved"))
        version = (request.context or {}).get("version")
        actor = request.user_id or (request.context or {}).get("owner") or ""
        if not name:
            catalog = [
                {"name": s.name, "permission": s.permission.value, "version": s.version}
                for s in self.skills.list_skills()
            ]
            timeline.append(TimelineStatus("completed", "skill catalog"))
            return OrchestratorResult(ok=True, reply="skill catalog", timeline=timeline, meta={"skills": catalog})
        timeline.append(TimelineStatus("executing", f"skill:{name}"))
        if version:
            result = self.skills.invoke_version(name, str(version), args, approved=approved, actor=actor)
        else:
            result = self.skills.invoke(name, args, approved=approved, actor=actor)
        if result.meta.get("needs_approval"):
            return OrchestratorResult(
                ok=False,
                needs_approval=True,
                reply="owner approval required for skill",
                timeline=timeline + [TimelineStatus("waiting_for_approval", name)],
                meta={"skill": name, "permission": result.meta.get("permission"), "version": result.meta.get("version")},
                error=result.error,
            )
        if result.ok:
            try:
                from pfai.longevity.autonomous_training.experience_bridge import notify_skill_success

                summary = result.reply or (str(result.output) if result.output is not None else "skill completed")
                notify_skill_success(
                    skill=name,
                    summary=str(summary)[:2000],
                    source_id=f"skill:{name}:{result.meta.get('version') or ''}",
                )
            except Exception:
                pass
        return OrchestratorResult(
            ok=result.ok,
            reply=result.reply or (str(result.output) if result.output is not None else ""),
            timeline=timeline + [TimelineStatus("completed" if result.ok else "failed", name)],
            meta={"skill": name, "output": result.output, "version": result.meta.get("version")},
            error=result.error,
        )

    def _run_memory(self, request: OrchestratorRequest, timeline: list[TimelineStatus]) -> OrchestratorResult:
        if self.ltm is None:
            return OrchestratorResult(ok=False, error="ltm not connected", timeline=timeline)
        action = (request.context or {}).get("action") or "query"
        if action == "store":
            kind = (request.context or {}).get("kind") or MemoryKind.SEMANTIC.value
            rec = self.ltm.store(
                MemoryRecord(
                    record_id=(request.context or {}).get("record_id") or "",
                    kind=kind,
                    content=request.goal,
                    source=(request.context or {}).get("source") or "orchestrator",
                    confidence=float((request.context or {}).get("confidence") or 0.7),
                )
            )
            timeline.append(TimelineStatus("completed", "ltm stored"))
            return OrchestratorResult(ok=True, reply="stored", timeline=timeline, meta={"record_id": rec.record_id, "version": rec.version})
        hits = self.ltm.query(query=request.goal, limit=int((request.context or {}).get("limit") or 10))
        timeline.append(TimelineStatus("completed", f"ltm hits={len(hits)}"))
        return OrchestratorResult(
            ok=True,
            reply=f"found {len(hits)} memories",
            timeline=timeline,
            meta={"hits": [{"id": h.record_id, "kind": h.kind, "content": h.content[:200]} for h in hits]},
        )

    def _run_knowledge(self, request: OrchestratorRequest, timeline: list[TimelineStatus]) -> OrchestratorResult:
        if self.knowledge_search is None:
            return OrchestratorResult(ok=False, error="knowledge not connected", timeline=timeline)
        limit = int((request.context or {}).get("limit") or 5)
        results = self.knowledge_search(request.goal, limit)
        timeline.append(TimelineStatus("completed", f"knowledge hits={len(results) if isinstance(results, list) else 1}"))
        return OrchestratorResult(ok=True, reply="knowledge search", timeline=timeline, meta={"results": results})

    def _run_learning(self, request: OrchestratorRequest, timeline: list[TimelineStatus]) -> OrchestratorResult:
        if self.learning is None:
            return OrchestratorResult(ok=False, error="learning pipeline not connected", timeline=timeline)
        if self.learning.allows_weight_mutation():
            return OrchestratorResult(ok=False, error="refusing learning path that allows weight mutation", timeline=timeline)
        action = (request.context or {}).get("action") or "ingest"
        source = (request.context or {}).get("source") or LearningSource.FEEDBACK.value
        if action == "readiness":
            return OrchestratorResult(ok=True, reply="training readiness", timeline=timeline, meta=self.learning.training_readiness())
        if action == "ingest":
            cand = self.learning.ingest(source, request.goal, meta=dict((request.context or {}).get("meta") or {}))
            timeline.append(TimelineStatus("completed", "learning ingested"))
            return OrchestratorResult(ok=True, reply="candidate proposed", timeline=timeline, meta={"candidate_id": cand.candidate_id, "status": str(cand.status)})
        cid = (request.context or {}).get("candidate_id")
        if not cid:
            return OrchestratorResult(ok=False, error="candidate_id required", timeline=timeline)
        if action == "evaluate":
            cand = self.learning.evaluate(cid)
        elif action == "validate":
            approved = bool((request.context or {}).get("approved"))
            if request.require_owner_for_sensitive and not approved:
                return OrchestratorResult(
                    ok=False,
                    needs_approval=True,
                    reply="owner approval required to validate learning",
                    timeline=timeline + [TimelineStatus("waiting_for_approval", "learning.validate")],
                    meta={"candidate_id": cid},
                )
            cand = self.learning.validate(cid, approved=approved)
        elif action == "store":
            cand = self.learning.store(cid)
        elif action == "rollback":
            cand = self.learning.rollback(cid)
        else:
            return OrchestratorResult(ok=False, error=f"unknown learning action: {action}", timeline=timeline)
        timeline.append(TimelineStatus("completed", f"learning.{action}"))
        return OrchestratorResult(
            ok=True,
            reply=f"learning {action} → {cand.status}",
            timeline=timeline,
            meta={"candidate_id": cand.candidate_id, "status": str(cand.status), "knowledge_id": (cand.meta or {}).get("knowledge_id")},
        )

    def _run_eval(self, request: OrchestratorRequest, timeline: list[TimelineStatus]) -> OrchestratorResult:
        if self.evaluation is None:
            return OrchestratorResult(ok=False, error="evaluation not connected", timeline=timeline)
        suite = (request.context or {}).get("suite") or "smoke"
        if (request.context or {}).get("action") == "compare":
            report = self.evaluation.compare(
                (request.context or {}).get("baseline_id") or "baseline",
                (request.context or {}).get("candidate_id") or "candidate",
                suite=suite,
            )
            timeline.append(TimelineStatus("completed", "version compare"))
            return OrchestratorResult(
                ok=True,
                reply="compare done",
                timeline=timeline,
                meta={
                    "ok_to_promote": report.ok_to_promote,
                    "regressions": report.regressions,
                    "baseline_score": report.baseline_score,
                    "candidate_score": report.candidate_score,
                },
            )
        report = self.evaluation.run_suite(suite)
        timeline.append(TimelineStatus("completed", f"eval {suite}"))
        return OrchestratorResult(
            ok=report.ok,
            reply=f"eval passed={report.passed} failed={report.failed}",
            timeline=timeline,
            meta={"suite": report.suite, "fingerprint": report.fingerprint, "cases": report.cases},
        )

    def _run_self_check(self, request: OrchestratorRequest, timeline: list[TimelineStatus]) -> OrchestratorResult:
        if self.self_check is None:
            return OrchestratorResult(ok=False, error="self_check not connected", timeline=timeline)
        report = self.self_check.run_checks()
        timeline.append(TimelineStatus("completed", report.summary))
        return OrchestratorResult(ok=report.ok, reply=report.summary, timeline=timeline, meta={"checks": report.checks})

    def _run_self_heal(self, request: OrchestratorRequest, timeline: list[TimelineStatus]) -> OrchestratorResult:
        if self.self_heal is None or self.self_check is None:
            return OrchestratorResult(ok=False, error="self_heal not connected", timeline=timeline)
        report = self.self_check.run_checks()
        proposal = self.self_heal.propose_fix(report)
        approved = bool((request.context or {}).get("approved"))
        if proposal.requires_owner and not approved:
            return OrchestratorResult(
                ok=False,
                needs_approval=True,
                approval_id=proposal.proposal_id,
                reply="owner approval required for heal",
                timeline=timeline + [TimelineStatus("waiting_for_approval", proposal.diagnosis)],
                meta={"proposal": {"id": proposal.proposal_id, "safe": proposal.safe, "steps": proposal.steps}},
            )
        applied = self.self_heal.apply_fix(proposal.proposal_id, approved=approved)
        tested = self.self_heal.test_fix(proposal.proposal_id)
        if not tested.ok:
            rolled = self.self_heal.rollback_fix(proposal.proposal_id)
            return OrchestratorResult(
                ok=False,
                reply="heal failed recheck; rolled back",
                timeline=timeline + [TimelineStatus("failed", "recheck"), TimelineStatus("completed", "rollback")],
                meta={"applied": applied.meta, "tested": tested.meta, "rollback": rolled.meta},
            )
        timeline.append(TimelineStatus("completed", "heal ok"))
        return OrchestratorResult(ok=True, reply="heal applied and tested", timeline=timeline, meta={"proposal_id": proposal.proposal_id})


def _looks_coding(text: str) -> bool:
    t = (text or "").lower()
    keys = ("python", "code", "coding", "debug", "sandbox", "علمني", "برمجة", "كود")
    return any(k in t for k in keys)
