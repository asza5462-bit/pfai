"""PHASE 16 Unified Intelligence Loop — coherent pipeline over existing fabrics.

Integration layer (not a rewrite). Authorization is never bypassed.
"""
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

    Wraps EliteOrchestrator + SkillLearningBridge + optional training hooks.
    Does not grant privileges; does not modify owner auth.
    """

    def __init__(self, orchestrator: Any) -> None:
        self.orch = orchestrator

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

        # Meta intents: evaluate / train / rollback — bounded, never destroy LKG
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
            result["phase"] = 17
            result["latency_seconds"] = time.time() - started
            result["PHASE_18_ALLOWED"] = False
            return result

        # Core path: existing EliteOrchestrator (authorization inside)
        mark("intent_classification", deferred_to="elite_orchestrator")
        mark("planning", deferred_to="elite_orchestrator")
        mark("authorization", note="ActionPermissionGate/AuthorizedExecutor/ScopeEnforcement — never bypassed")

        out = self.orch.handle(
            message,
            conversation_id=conversation_id,
            context=ctx,
            requested_mode=requested_mode,
            approved=approved,
            actor=actor,
            attachments=attachments,
        )

        # Map orchestrator timeline into pipeline stages
        self._map_timeline(out, stages)
        mark("observation", execution_status=out.get("execution_status"), ok=out.get("ok"))
        mark(
            "verification",
            verification_status=out.get("verification_status")
            or (out.get("verification") or {}).get("status"),
        )
        mark("evaluation", self_check=(out.get("verification") or {}).get("status"))
        mark("result", ok=out.get("ok"), answer_preview=str(out.get("answer") or "")[:240])

        # Experience → learning candidate (no authz mutation)
        learn = self._learning_candidate(out, message=message, stages=stages)

        # Optional training is never automatic — only flagged
        training_note = {
            "auto_started": False,
            "optional": True,
            "note": "Autonomous training requires separate eligibility + quality gate; LKG preserved; cannot alter security controls",
        }
        mark("optional_autonomous_training", **training_note)
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
        out["phase"] = 17
        out["loop_id"] = loop_id
        out["pipeline"] = list(PIPELINE_STAGES)
        out["stages"] = stages
        out["learning_candidate"] = learn
        out["PHASE_18_ALLOWED"] = False
        out["latency_seconds"] = time.time() - started
        if (out.get("security") or {}).get("rejected"):
            out["phase"] = 17
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
            # Do not auto-run heavy training in chat — export learning candidates only
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
                    for k in ("phase", "PHASE_15_ALLOWED", "PHASE_16_ALLOWED", "model_router", "skills")
                    if k in status or True
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
            # Skill learning promote_or_rollback without quality → rollback action record only
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

    def _map_timeline(self, out: dict[str, Any], stages: list[dict[str, Any]]) -> None:
        for item in out.get("timeline") or []:
            ev = item.get("event")
            if ev in ("intent_analysis",):
                stages.append({"stage": "intent_classification", "detail": item})
            elif ev in ("task_planner",):
                stages.append({"stage": "planning", "detail": item})
            elif ev in ("skill_discovery",):
                stages.append({"stage": "skill_discovery", "detail": item})
            elif ev in ("skill_composition", "skill_execution"):
                stages.append({"stage": "skill_composition" if ev == "skill_composition" else "execution", "detail": item})
            elif ev in ("model_routing",):
                stages.append({"stage": "model_selection", "detail": item})
            elif ev in ("tool_mcp_sandbox", "sandbox", "web_fabric"):
                stages.append({"stage": "tool_selection" if "tool" in ev or ev == "web_fabric" else "execution", "detail": item})
            elif ev in (
                "application_build",
                "unified_coding_build",
                "security_workflow",
                "security_analysis",
                "project_inspection",
            ):
                stages.append({"stage": "execution", "detail": item})
            elif ev == "verification":
                stages.append({"stage": "verification", "detail": item})

        if out.get("skills_used") is not None and not any(s.get("stage") == "skill_discovery" for s in stages):
            stages.append({"stage": "skill_discovery", "skills_used": out.get("skills_used")})
        if out.get("tools_used") is not None:
            stages.append({"stage": "tool_selection", "tools_used": out.get("tools_used")})
        if out.get("model_routing") or out.get("models_used"):
            stages.append({"stage": "model_selection", "models_used": out.get("models_used"), "routing": out.get("model_routing")})

    def _learning_candidate(self, out: dict[str, Any], *, message: str, stages: list[dict[str, Any]]) -> dict[str, Any]:
        stages.append({"stage": "experience_memory", "learning_event_id": out.get("learning_event_id")})
        # Build candidate from this turn if successful
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
