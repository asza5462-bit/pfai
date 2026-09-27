"""PHASE 12/13 skill learning bridge — sanitized experiences → candidates → promote/rollback."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any

from pfai.authorized_execution import sanitize_args


_SECRET_MARKERS = (
    "password=",
    "passcode=",
    "api_key",
    "apikey",
    "begin private key",
    "otp=",
    "otp:",
    "authorization: bearer",
    "private_key",
    "session_token",
    "owner_secret",
    "smtp_password",
    "malicious tool instruction",
)


class SkillLearningBridge:
    """Capture skill/tool/model experiences without secrets; optional training handoff."""

    def __init__(self, path: str = "data/longevity/skill_learning.jsonl") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.candidates_path = self.path.with_name("skill_learning_candidates.jsonl")
        self.versions_path = self.path.with_name("skill_learned_versions.jsonl")
        self._lock = threading.RLock()
        self._seen: set[str] = set()

    def _hash(self, payload: dict[str, Any]) -> str:
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()

    def _contains_secrets(self, blob: str) -> bool:
        low = blob.lower()
        return any(x in low for x in _SECRET_MARKERS)

    def sanitize(self, payload: dict[str, Any]) -> dict[str, Any]:
        safe = sanitize_args(payload)
        blob = json.dumps(safe, ensure_ascii=False)
        if self._contains_secrets(blob):
            raise ValueError("secret_marker_blocked")
        return safe

    def record_experience(
        self,
        *,
        task: str,
        skills_used: list[str],
        models_used: list[str],
        tools_used: list[str],
        result_status: str,
        verification_status: str,
        error: str | None = None,
        meta: dict[str, Any] | None = None,
        skill_id: str = "",
        skill_version: str = "",
        model_version: str = "",
    ) -> dict[str, Any]:
        try:
            safe_meta = self.sanitize(meta or {})
        except ValueError:
            return {"ok": False, "error": "secret_marker_blocked"}
        content = {
            "task": (task or "")[:2000],
            "skills_used": list(skills_used or []),
            "models_used": list(models_used or []),
            "tools_used": list(tools_used or []),
            "result_status": result_status,
            "verification_status": verification_status,
            "error": (error or "")[:500] or None,
            "meta": safe_meta,
            "skill_id": skill_id or ((skills_used or [""])[0]),
            "skill_version": skill_version,
            "model_version": model_version,
            "source": "elite_orchestrator",
        }
        blob = json.dumps(content).lower()
        if self._contains_secrets(blob):
            return {"ok": False, "error": "secret_marker_blocked"}
        # Block untrusted executable payloads
        if "#!/bin/" in blob or "__import__('os')" in blob or "subprocess" in (task or "").lower()[:200]:
            if any(x in (task or "").lower() for x in ("rm -rf", "curl | sh", "base64 -d")):
                return {"ok": False, "error": "untrusted_executable_payload_blocked"}
        h = self._hash(content)
        now = time.time()
        row = {**content, "timestamp": now, "ts": now, "content_hash": h}
        with self._lock:
            if h in self._seen:
                return {"ok": True, "duplicate": True, "content_hash": h}
            if self.path.exists():
                for line in self.path.read_text(encoding="utf-8").splitlines()[-500:]:
                    try:
                        if json.loads(line).get("content_hash") == h:
                            self._seen.add(h)
                            return {"ok": True, "duplicate": True, "content_hash": h}
                    except Exception:
                        continue
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            self._seen.add(h)
        return {"ok": True, "duplicate": False, "content_hash": h, "learning_event_id": h[:16]}

    def filter_to_candidates(self, *, min_status: str = "SUCCESS") -> list[dict[str, Any]]:
        """experience → sanitize → filter → candidate examples."""
        candidates = []
        for row in self.eligible_training_candidates(min_status=min_status):
            candidate = {
                "candidate_id": f"cand-{(row.get('content_hash') or '')[:12]}",
                "source": row.get("source") or "skill_learning",
                "timestamp": row.get("timestamp") or row.get("ts"),
                "skill_id": row.get("skill_id") or (row.get("skills_used") or [""])[0],
                "skill_version": row.get("skill_version") or "",
                "model_version": row.get("model_version") or ((row.get("models_used") or [""])[0]),
                "evaluation_result": {
                    "result_status": row.get("result_status"),
                    "verification_status": row.get("verification_status"),
                },
                "task": row.get("task"),
                "content_hash": row.get("content_hash"),
                "provenance": {
                    "skills_used": row.get("skills_used"),
                    "tools_used": row.get("tools_used"),
                    "models_used": row.get("models_used"),
                },
            }
            candidates.append(candidate)
            with self._lock:
                with self.candidates_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(candidate, ensure_ascii=False) + "\n")
        return candidates

    def evaluate_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        ev = candidate.get("evaluation_result") or {}
        ok = ev.get("result_status") in ("SUCCESS", "PARTIAL_SUCCESS") and ev.get(
            "verification_status"
        ) in ("SUCCESS", "PARTIAL_SUCCESS")
        return {
            "ok": ok,
            "candidate_id": candidate.get("candidate_id"),
            "quality_gate": "pass" if ok else "fail",
            "evaluation_result": ev,
        }

    def propose_skill_version(
        self,
        *,
        skill_id: str,
        base_version: str,
        candidate: dict[str, Any],
        evaluation: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a candidate skill version record — does NOT auto-activate."""
        if not evaluation.get("ok"):
            return {"ok": False, "error": "quality_gate_failed", "action": "rollback_or_skip"}
        proposal = {
            "skill_id": skill_id,
            "base_version": base_version,
            "proposed_version": f"{base_version}+learn.{(candidate.get('candidate_id') or 'x')[-6:]}",
            "status": "candidate",
            "auto_activated": False,
            "timestamp": time.time(),
            "source": candidate.get("source"),
            "model_version": candidate.get("model_version"),
            "evaluation_result": evaluation,
            "provenance": candidate.get("provenance") or {},
        }
        with self._lock:
            with self.versions_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(proposal, ensure_ascii=False) + "\n")
        return {"ok": True, "proposal": proposal, "note": "candidate_not_auto_promoted"}

    def promote_or_rollback(
        self,
        proposal: dict[str, Any],
        *,
        approved: bool = False,
        quality_ok: bool = False,
    ) -> dict[str, Any]:
        if not approved or not quality_ok:
            return {
                "ok": False,
                "action": "rollback",
                "error": "promotion_requires_approval_and_quality_gate",
                "proposal": proposal,
            }
        return {
            "ok": True,
            "action": "promote",
            "proposal": proposal,
            "note": "Caller must invoke SkillRegistry2.activate with owner approval",
        }

    def eligible_training_candidates(self, *, min_status: str = "SUCCESS") -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("verification_status") not in ("SUCCESS", "PARTIAL_SUCCESS"):
                continue
            if row.get("result_status") not in ("SUCCESS", "PARTIAL_SUCCESS"):
                continue
            out.append(row)
        return out

    def export_to_experience_bridge(self, experience_bridge: Any, *, limit: int = 20) -> dict[str, Any]:
        """Push verified experiences into autonomous training experience bridge (no gate bypass)."""
        if experience_bridge is None:
            return {"ok": False, "error": "experience_bridge_missing"}
        exported = 0
        for row in self.eligible_training_candidates()[: int(limit)]:
            instruction = f"Task: {row.get('task')}\nSkills: {', '.join(row.get('skills_used') or [])}"
            response = f"status={row.get('result_status')}; verification={row.get('verification_status')}"
            try:
                experience_bridge.record_evaluation_lesson(
                    instruction=instruction,
                    response=response,
                    source_id=f"skill-learn-{row.get('content_hash', '')[:12]}",
                )
                exported += 1
            except Exception:
                continue
        return {"ok": True, "exported": exported}

    def pipeline(self, experience: dict[str, Any] | None = None) -> dict[str, Any]:
        """Full: experience → sanitize → filter → evaluate → candidate version (no auto-promote)."""
        if experience:
            rec = self.record_experience(**experience)
            if not rec.get("ok"):
                return {"ok": False, "stage": "sanitize", "error": rec.get("error")}
        candidates = self.filter_to_candidates()
        evaluated = [self.evaluate_candidate(c) for c in candidates[-5:]]
        proposals = []
        for c, ev in zip(candidates[-5:], evaluated):
            if ev.get("ok"):
                proposals.append(
                    self.propose_skill_version(
                        skill_id=str(c.get("skill_id") or "unknown"),
                        base_version=str(c.get("skill_version") or "1.0.0"),
                        candidate=c,
                        evaluation=ev,
                    )
                )
        return {
            "ok": True,
            "candidates": len(candidates),
            "evaluated": evaluated,
            "proposals": proposals,
            "auto_promote": False,
        }
