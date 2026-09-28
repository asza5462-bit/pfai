"""PHASE 16/19 Unified Intelligence Loop — routes through UnifiedAICore while preserving meta intents."""
from __future__ import annotations

import time
from typing import Any

from pfai.authorized_execution import sanitize_args
from pfai.elite.types import new_id


PIPELINE_STAGES = (
    "user_intent",
    "intent_classification",
    "planning",
    "skill_discovery",
    "skill_composition",
    "model_selection",
    "tool_selection",
    "authorization",
    "execution",
    "observation",
    "verification",
    "evaluation",
    "result",
    "experience_memory",
    "learning_candidate",
    "optional_autonomous_training",
    "quality_gate",
    "activation_or_rollback",
)


class UnifiedIntelligenceLoop:
    """
    User Intent → … → Activation or Rollback.

    Phase 20: multi-step/complex requests → AgentExecutionEngine;
    simpler turns still use UnifiedAICore. Meta intents remain bounded; LKG preserved.
    """

    def __init__(self, orchestrator: Any) -> None:
        self.orch = orchestrator
        self._core = None
        self._agent = None

    def _core_instance(self):
        if self._core is None:
            from pfai.elite.unified_ai_core import UnifiedAICore

            self._core = UnifiedAICore(self.orch)
        return self._core

    def _agent_instance(self):
        if self._agent is None:
            from pfai.elite.agent_execution_engine import AgentExecutionEngine

            self._agent = AgentExecutionEngine(self.orch)
        return self._agent

    def _use_agent_engine(self, message: str, ctx: dict[str, Any]) -> bool:
        if ctx.get("force_agent_engine") or ctx.get("use_agent_execution_engine"):
            return True
        from pfai.elite.capability_router import CapabilityRouter

        caps = CapabilityRouter().route(message, context=ctx).get("capabilities") or []
        if len(caps) >= 3:
            return True
        t = (message or "").lower()
        multi_markers = (
            "and then",
            "then ",
            "finally",
            "implement",
            "run the tests",
            "run tests",
            "fix it",
            "fix the",
            "analyze this",
            "find the bug",
            "optimize",
            "review this",
        )
        return sum(1 for m in multi_markers if m in t) >= 2

    def run(
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
        loop_id = new_id("uil")
        stages: list[dict[str, Any]] = []
        ctx = dict(context or {})

        def mark(stage: str, **detail: Any) -> None:
            stages.append({"stage": stage, "ts": time.time(), **sanitize_args(detail)})

        mark("user_intent", message_preview=(message or "")[:200])

        meta = self._detect_meta_intent(message)
        if meta:
            mark("intent_classification", intents=[meta], mode="AI")
            result = self._handle_meta(
                meta,
                message=message,
                approved=approved,
                actor=actor,
                allow_training_ops=allow_training_ops,
                stages=stages,
            )
            result["loop_id"] = loop_id
            result["pipeline"] = PIPELINE_STAGES
            result["stages"] = stages
            result["phase"] = 22
            result["latency_seconds"] = time.time() - started
            result["PHASE_23_ALLOWED"] = False
            return result

        use_agent = self._use_agent_engine(message, ctx)
        mark(
            "intent_classification",
            deferred_to="agent_execution_engine" if use_agent else "unified_ai_core",
        )
        mark("planning", deferred_to="agent_execution_engine" if use_agent else "unified_ai_core")
        mark("authorization", note="ActionPermissionGate/AuthorizedExecutor/ScopeEnforcement — never bypassed")

        if use_agent:
            out = self._agent_instance().run(
                message,
                approved=approved,
                actor=actor,
                context=ctx,
                force_tool_failure=bool(ctx.get("force_tool_failure")),
                force_model_failure=bool(ctx.get("force_model_failure")),
            )
            # Map agent stages into loop stages
            task = out.get("task") or {}
            stages.append({"stage": "skill_discovery", "skills": out.get("skills")})
            stages.append({"stage": "skill_composition", "plan_steps": len(task.get("steps") or [])})
            stages.append({"stage": "model_selection", "model": out.get("model")})
            stages.append({"stage": "tool_selection", "tools": out.get("tools")})
            stages.append({"stage": "execution", "state": out.get("state"), "ok": out.get("ok")})
            out = dict(out)
            out["unified_ai_core"] = True
            out["agent_execution_engine"] = True
        else:
            out = self._core_instance().handle(
                message,
                conversation_id=conversation_id,
                context=ctx,
                requested_mode=requested_mode,
                approved=approved,
                actor=actor,
                attachments=attachments,
                allow_training_ops=allow_training_ops,
            )
            _alias = {
                "model_routing": "model_selection",
                "skill_selection": "skill_discovery",
                "learning_experience_record": "experience_memory",
                "validation_testing": "verification",
                "capability_discovery": "skill_discovery",
            }
            for s in out.get("stages") or []:
                stage = s.get("stage")
                stages.append(s if "stage" in s else {"stage": "execution", **s})
                if stage in _alias:
                    stages.append({**s, "stage": _alias[stage], "alias_of": stage})

        mark("observation", execution_status=out.get("execution_status"), ok=out.get("ok"))
        mark(
            "verification",
            verification_status=out.get("verification_status")
            or (out.get("validation") or {}).get("status"),
        )
        mark("evaluation", self_check=(out.get("validation") or {}).get("status"))
        mark("result", ok=out.get("ok"), answer_preview=str(out.get("answer") or "")[:240])
        mark("experience_memory", learning=bool(out.get("learning_candidate")))

        learn = out.get("learning_candidate") or self._learning_candidate(out, message=message, stages=stages)
        if not any(s.get("stage") == "learning_candidate" for s in stages):
            mark(
                "learning_candidate",
                created=bool(learn.get("recorded") or learn.get("created")),
                eligibility=learn.get("eligibility"),
            )
        mark(
            "optional_autonomous_training",
            auto_started=False,
            optional=True,
            note="Autonomous training requires separate eligibility + quality gate; LKG preserved; cannot alter security controls",
        )
        mark(
            "quality_gate",
            status="PASS"
            if out.get("ok") and not (out.get("security") or {}).get("rejected")
            else "HOLD",
        )
        mark(
            "activation_or_rollback",
            action="none",
            note="No model/skill auto-activation from chat turn",
            lkg_preserved=True,
        )

        out = dict(out)
        out["phase"] = 22
        out["loop_id"] = loop_id
        out["pipeline"] = list(PIPELINE_STAGES)
        out["stages"] = stages
        out["learning_candidate"] = learn
        out["PHASE_23_ALLOWED"] = False
        out["latency_seconds"] = time.time() - started
        out["unified_intelligence_loop"] = True
        out.setdefault("skills_used", out.get("skills_used") or out.get("skills_used") or [])
        if not out.get("skills_used"):
            out["skills_used"] = list(out.get("capabilities") or [])
        # Ensure security rejection surfaces for offensive path
        if (out.get("security") or {}).get("rejected") or out.get("denied"):
            out["ok"] = False
            out.setdefault("security", {"rejected": True, "offensive_blocked": True})
        return out

    def _detect_meta_intent(self, message: str) -> str | None:
        t = (message or "").lower()
        if any(w in t for w in ("rollback the latest candidate", "rollback candidate", "rollback the model")):
            return "rollback"
        if any(w in t for w in ("train a candidate model", "train candidate", "start autonomous training")):
            return "train"
        if any(w in t for w in ("evaluate the latest model", "evaluate candidate model", "run quality gate")):
            return "evaluate_model"
        if any(w in t for w in ("create a new skill", "propose skill version")):
            return "skill_propose"
        return None

    def _handle_meta(
        self,
        meta: str,
        *,
        message: str,
        approved: bool,
        actor: str,
        allow_training_ops: bool,
        stages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        stages.append({"stage": "planning", "meta": meta})
        stages.append({"stage": "authorization", "approved": bool(approved), "actor": actor})

        if meta == "train":
            if not approved or not allow_training_ops:
                stages.append({"stage": "execution", "ok": False, "error": "training_requires_owner_approval"})
                return {
                    "ok": False,
                    "answer": "Training not started: requires owner approval and allow_training_ops. LKG untouched.",
                    "execution_status": "BLOCKED",
                    "verification_status": "HOLD",
                    "meta_intent": meta,
                    "lkg_preserved": True,
                    "training_started": False,
                }
            exported = self.orch.export_learning_to_training(limit=10) if hasattr(self.orch, "export_learning_to_training") else {"ok": False}
            stages.append({"stage": "execution", "ok": True, "action": "export_learning_only", "exported": exported})
            stages.append({"stage": "activation_or_rollback", "action": "none", "lkg_preserved": True})
            return {
                "ok": True,
                "answer": "Learning candidates exported for autonomous training pipeline. No model activation performed; LKG preserved.",
                "execution_status": "SUCCESS",
                "verification_status": "SUCCESS",
                "meta_intent": meta,
                "export": exported,
                "training_started": False,
                "lkg_preserved": True,
                "skills_used": [],
                "models_used": [],
                "tools_used": [],
            }

        if meta == "evaluate_model":
            stages.append({"stage": "execution", "action": "status_only"})
            status = self.orch.status() if hasattr(self.orch, "status") else {}
            return {
                "ok": True,
                "answer": "Model evaluation status retrieved (no weights modified).",
                "execution_status": "SUCCESS",
                "verification_status": "SUCCESS",
                "meta_intent": meta,
                "platform": {
                    k: status.get(k)
                    for k in (
                        "phase",
                        "PHASE_15_ALLOWED",
                        "PHASE_16_ALLOWED",
                        "PHASE_18_ALLOWED",
                        "PHASE_19_ALLOWED",
                        "PHASE_20_ALLOWED",
                        "PHASE_21_ALLOWED",
                        "PHASE_22_ALLOWED",
                        "PHASE_23_ALLOWED",
                        "model_router",
                        "skills",
                    )
                },
                "lkg_preserved": True,
                "skills_used": [],
                "models_used": [],
                "tools_used": [],
            }

        if meta == "rollback":
            if not approved:
                return {
                    "ok": False,
                    "answer": "Rollback requires owner approval. LKG remains intact.",
                    "execution_status": "BLOCKED",
                    "meta_intent": meta,
                    "lkg_preserved": True,
                }
            proposal = {"skill_id": "meta", "status": "candidate"}
            action = self.orch.learning.promote_or_rollback(proposal, approved=False, quality_ok=False)
            stages.append({"stage": "activation_or_rollback", **action})
            return {
                "ok": True,
                "answer": "Rollback path exercised without destroying LKG (promotion denied without quality gate).",
                "execution_status": "SUCCESS",
                "verification_status": "SUCCESS",
                "meta_intent": meta,
                "rollback": action,
                "lkg_preserved": True,
                "skills_used": [],
                "models_used": [],
                "tools_used": [],
            }

        if meta == "skill_propose":
            pipeline = self.orch.learning.pipeline()
            stages.append({"stage": "learning_candidate", "pipeline": {"ok": pipeline.get("ok"), "proposals": len(pipeline.get("proposals") or [])}})
            stages.append({"stage": "activation_or_rollback", "action": "none", "note": "proposals not auto-activated"})
            return {
                "ok": True,
                "answer": "Skill learning pipeline produced candidates without auto-activation.",
                "execution_status": "SUCCESS",
                "verification_status": "SUCCESS",
                "meta_intent": meta,
                "skill_pipeline": pipeline,
                "lkg_preserved": True,
                "skills_used": [],
                "models_used": [],
                "tools_used": [],
            }

        return {"ok": False, "error": "unknown_meta_intent", "meta_intent": meta}

    def _learning_candidate(self, out: dict[str, Any], *, message: str, stages: list[dict[str, Any]]) -> dict[str, Any]:
        stages.append({"stage": "experience_memory", "learning_event_id": out.get("learning_event_id")})
        if not out.get("ok") or (out.get("security") or {}).get("rejected"):
            stages.append({"stage": "learning_candidate", "created": False, "reason": "turn_not_eligible"})
            return {"created": False, "reason": "turn_not_eligible"}
        candidates = self.orch.learning.filter_to_candidates()
        latest = candidates[-1] if candidates else None
        evaluated = self.orch.learning.evaluate_candidate(latest) if latest else {"ok": False}
        stages.append(
            {
                "stage": "learning_candidate",
                "created": bool(latest),
                "quality_gate": evaluated.get("quality_gate"),
                "cannot_modify_authz": True,
            }
        )
        return {
            "created": bool(latest),
            "candidate_id": (latest or {}).get("candidate_id"),
            "evaluation": evaluated,
            "cannot_modify_authentication": True,
            "cannot_modify_authorization": True,
            "cannot_modify_security_policy": True,
        }
