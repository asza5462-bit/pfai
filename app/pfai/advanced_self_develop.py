"""Advanced self-develop stage — aware, multi-pass, autonomous within safe bounds.

When continuous learning matures, this stage:
  - reports what it is doing (awareness / metacognition)
  - builds code with generate → verify → review → repair → re-verify (multi-pass)
  - curates only sandbox-verified solutions into continuous learning
  - never silently promotes model weights

"No human click" applies to curation + safe heal + self-build loops.
Weight activation / security / SSRF remain gated.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger("pfai.advanced_self_develop")

# Micro-curriculum: tiny verified tasks so the loop can self-train without waiting.
_CURRICULUM: list[dict[str, str]] = [
    {
        "id": "sum_list",
        "instruction": "Write a function solve(xs) that returns the sum of a list of integers.",
        "test_code": (
            "assert solve([]) == 0\n"
            "assert solve([1,2,3]) == 6\n"
            "assert solve([-1,1]) == 0\n"
        ),
        "reference": "def solve(xs):\n    return sum(xs)\n",
    },
    {
        "id": "max_of_two",
        "instruction": "Write a function solve(a, b) that returns the larger of two numbers.",
        "test_code": (
            "assert solve(1, 2) == 2\n"
            "assert solve(5, 5) == 5\n"
            "assert solve(-3, -1) == -1\n"
        ),
        "reference": "def solve(a, b):\n    return a if a >= b else b\n",
    },
    {
        "id": "is_even",
        "instruction": "Write a function solve(n) that returns True if n is even else False.",
        "test_code": (
            "assert solve(2) is True\n"
            "assert solve(3) is False\n"
            "assert solve(0) is True\n"
        ),
        "reference": "def solve(n):\n    return n % 2 == 0\n",
    },
    {
        "id": "reverse_string",
        "instruction": "Write a function solve(s) that returns the reversed string.",
        "test_code": (
            "assert solve('ab') == 'ba'\n"
            "assert solve('') == ''\n"
            "assert solve('xyz') == 'zyx'\n"
        ),
        "reference": "def solve(s):\n    return s[::-1]\n",
    },
    {
        "id": "count_vowels",
        "instruction": "Write a function solve(s) that counts English vowels aeiou (case-insensitive).",
        "test_code": (
            "assert solve('hello') == 2\n"
            "assert solve('AEIOU') == 5\n"
            "assert solve('xyz') == 0\n"
        ),
        "reference": (
            "def solve(s):\n"
            "    return sum(1 for ch in s.lower() if ch in 'aeiou')\n"
        ),
    },
]


class AdvancedSelfDevelop:
    """Maturity-gated self-development brain for continuous learn + code build."""

    def __init__(
        self,
        *,
        code_learning: Any,
        continuous: Any,
        evaluator: Any = None,
        journal_path: str = "data/longevity/advanced_self_develop.jsonl",
        review_passes: int = 3,
        max_repairs: int = 6,
    ) -> None:
        self.code_learning = code_learning
        self.continuous = continuous
        self.evaluator = evaluator or getattr(code_learning, "evaluator", None)
        self.journal_path = Path(journal_path)
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        self.review_passes = max(2, int(review_passes))
        self.max_repairs = max(2, int(max_repairs))
        self._successes = 0
        self._attempts = 0
        self._last_awareness: dict[str, Any] = {}

    # -- awareness / maturity ---------------------------------------------
    def maturity(self) -> dict[str, Any]:
        cont = {}
        try:
            cont = self.continuous.status() if self.continuous else {}
        except Exception as exc:
            cont = {"error": str(exc)}
        hist = cont.get("learning_history") or []
        accepted = sum(1 for h in hist if (h or {}).get("status") in {"accepted", "active"})
        pending = int(cont.get("pending_examples") or 0)
        worker = bool(cont.get("worker_alive"))
        real_loop = bool(cont.get("real_loop"))
        score = 0
        reasons: list[str] = []
        if worker and real_loop:
            score += 1
            reasons.append("continuous_worker_alive")
        if pending >= 3 or accepted >= 2:
            score += 1
            reasons.append("curated_learning_mass")
        try:
            from pfai.open_execution import auto_accept_learning, auto_safe_heal
            if auto_accept_learning():
                score += 1
                reasons.append("auto_accept_learning")
            if auto_safe_heal():
                score += 1
                reasons.append("auto_safe_heal")
        except Exception:
            pass
        if self._successes >= 1 or accepted >= 5:
            score += 1
            reasons.append("verified_code_self_build")
        if score <= 1:
            stage = "emerging"
        elif score == 2:
            stage = "capable"
        elif score <= 4:
            stage = "advanced"
        else:
            stage = "sovereign_safe"
        return {
            "ok": True,
            "stage": stage,
            "score": score,
            "reasons": reasons,
            "pending_examples": pending,
            "accepted_candidates": accepted,
            "code_build_successes": self._successes,
            "code_build_attempts": self._attempts,
            "weight_promotion": "never_auto",
            "note": (
                "sovereign_safe = autonomous curation/heal/code-build within sandbox; "
                "weight promotion stays explicit"
            ),
        }

    def awareness(self, *, intent: str = "status") -> dict[str, Any]:
        mat = self.maturity()
        report = {
            "ok": True,
            "aware": True,
            "intent": intent,
            "stage": mat["stage"],
            "i_am_doing": {
                "continuous_learning": "curate + evaluate cycles (no silent promote)",
                "self_heal": "registered safe actions only",
                "code_self_build": f"multi-pass review×{self.review_passes} + repair≤{self.max_repairs}",
                "precision_rule": "accept only sandbox-verified code",
            },
            "i_will_not": [
                "silent_weight_promotion",
                "ssrf_bypass",
                "secret_read",
                "arbitrary_unsandboxed_exec",
            ],
            "maturity": mat,
            "last_cycle": self._last_awareness or None,
            "ts": time.time(),
        }
        self._last_awareness = {"awareness": True, "stage": mat["stage"], "ts": report["ts"]}
        return report

    def _journal(self, event: str, **payload: Any) -> None:
        row = {"ts": time.time(), "event": event, **payload}
        with self.journal_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    # -- multi-pass code build --------------------------------------------
    def _verify(self, code: str, test_code: str) -> dict[str, Any]:
        if self.evaluator is None:
            return {"ok": False, "passed": False, "reason": "no evaluator"}
        try:
            r = self.evaluator.evaluate(code, test_code)
            return {
                "ok": bool(r.passed),
                "passed": bool(r.passed),
                "reason": getattr(r, "reason", ""),
                "stderr": (getattr(r, "stderr", "") or "")[-800:],
            }
        except Exception as exc:
            return {"ok": False, "passed": False, "reason": str(exc)}

    def _review_critique(self, instruction: str, code: str, test_code: str, verify: dict) -> str:
        """Ask the teacher for a precision review; return revised code or same code."""
        model = getattr(self.code_learning, "model", None)
        if model is None or verify.get("passed"):
            return code
        prompt = (
            "You are a strict senior reviewer. The code FAILED tests. "
            "Return ONLY complete fixed Python code (no markdown).\n"
            f"TASK:\n{instruction}\n\nCODE:\n{code}\n\nTESTS:\n{test_code}\n\n"
            f"FAILURE:\n{verify.get('reason')}\n{verify.get('stderr')}\n"
            "Fix root cause. Do not weaken tests. Handle edge cases."
        )
        try:
            raw = (model.generate(prompt) or "").strip()
        except Exception:
            return code
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(
                lines[1:-1] if lines and lines[-1].strip().startswith("```") else lines[1:]
            ).strip()
        return raw or code

    def multi_pass_build(
        self,
        instruction: str,
        test_code: str,
        *,
        source: str = "advanced_self_develop",
        allow_reference: Optional[str] = None,
    ) -> dict[str, Any]:
        """Generate/repair with multiple independent verification passes."""
        self._attempts += 1
        passes_log: list[dict[str, Any]] = []
        code: Optional[str] = None
        origin = "model"

        # Pass A — pipeline (best-of-N + autofix + adversarial when available)
        try:
            pipe = self.code_learning.solve_and_learn(
                instruction, test_code, source=source, task_id=f"asd-{uuid.uuid4().hex[:8]}"
            )
        except Exception as exc:
            pipe = {"solved": False, "reason": str(exc), "curated": False}
        passes_log.append({"pass": "pipeline", "solved": bool(pipe.get("solved")), "reason": pipe.get("reason")})

        if pipe.get("solved") and pipe.get("code"):
            code = str(pipe["code"])
        elif allow_reference:
            # Curriculum teacher fallback — still must pass sandbox
            code = allow_reference
            origin = "curriculum_teacher"
            v0 = self._verify(code, test_code)
            passes_log.append({"pass": "teacher_seed", **v0})
            if not v0.get("passed"):
                return {
                    "ok": False,
                    "solved": False,
                    "curated": False,
                    "origin": origin,
                    "passes": passes_log,
                    "reason": "teacher seed failed verification",
                    "awareness": self.awareness(intent="multi_pass_build_failed"),
                }

        if not code:
            self._journal("build_failed", instruction=instruction[:200], passes=passes_log)
            return {
                "ok": False,
                "solved": False,
                "curated": False,
                "origin": origin,
                "passes": passes_log,
                "reason": pipe.get("reason") or "no verified code",
                "awareness": self.awareness(intent="multi_pass_build_failed"),
            }

        # Passes B..N — independent re-verify + critique/repair
        for i in range(1, self.review_passes + 1):
            v = self._verify(code, test_code)
            passes_log.append({"pass": f"review_{i}", **v})
            if v.get("passed"):
                continue
            code = self._review_critique(instruction, code, test_code, v)
            # Prefer autofix engine when present
            fixer = getattr(self.code_learning, "auto_fixer", None)
            if fixer is not None:
                try:
                    old = getattr(fixer, "max_repairs", 4)
                    fixer.max_repairs = self.max_repairs
                    repaired = fixer.solve_and_repair(instruction, code, test_code)
                    fixer.max_repairs = old
                    if repaired.solved and repaired.code:
                        code = repaired.code
                        passes_log.append({
                            "pass": f"repair_{i}",
                            "solved": True,
                            "repairs": repaired.repairs,
                        })
                    else:
                        passes_log.append({"pass": f"repair_{i}", "solved": False})
                        return {
                            "ok": False,
                            "solved": False,
                            "curated": False,
                            "origin": origin,
                            "passes": passes_log,
                            "reason": f"failed review pass {i}",
                            "awareness": self.awareness(intent="multi_pass_build_failed"),
                        }
                except Exception as exc:
                    passes_log.append({"pass": f"repair_{i}", "error": str(exc)})
                    return {
                        "ok": False,
                        "solved": False,
                        "curated": False,
                        "origin": origin,
                        "passes": passes_log,
                        "reason": str(exc),
                        "awareness": self.awareness(intent="multi_pass_build_failed"),
                    }

        final = self._verify(code, test_code)
        passes_log.append({"pass": "final", **final})
        if not final.get("passed"):
            return {
                "ok": False,
                "solved": False,
                "curated": False,
                "origin": origin,
                "passes": passes_log,
                "reason": "final verification failed",
                "awareness": self.awareness(intent="multi_pass_build_failed"),
            }

        curated = False
        if not pipe.get("curated"):
            try:
                cur = self.continuous.register_batch([{
                    "instruction": instruction,
                    "response": code,
                    "source": source,
                    "track": "software_engineering",
                    "metadata": {
                        "multi_pass": True,
                        "review_passes": self.review_passes,
                        "origin": origin,
                        "passes": passes_log,
                    },
                }])
                curated = int(cur.get("accepted") or 0) > 0
            except Exception as exc:
                passes_log.append({"pass": "curate", "error": str(exc)})
        else:
            curated = True

        self._successes += 1
        out = {
            "ok": True,
            "solved": True,
            "curated": curated,
            "code": code,
            "origin": origin,
            "passes": passes_log,
            "review_passes": self.review_passes,
            "weight_promotion": "never_auto",
            "awareness": self.awareness(intent="multi_pass_build_ok"),
        }
        self._journal("build_ok", origin=origin, curated=curated, passes=len(passes_log))
        self._last_awareness = {"build": "ok", "origin": origin, "ts": time.time()}
        return out

    def autonomous_cycle(
        self,
        *,
        force: bool = False,
        include_continuous_tick: bool = True,
    ) -> dict[str, Any]:
        """One self-directed develop cycle when stage is advanced enough."""
        mat = self.maturity()
        stage = mat["stage"]
        if not force and stage not in {"advanced", "sovereign_safe", "capable"}:
            report = {
                "ok": True,
                "ran": False,
                "reason": f"stage={stage} — still maturing",
                "maturity": mat,
                "awareness": self.awareness(intent="wait_for_maturity"),
            }
            self._journal("skipped_immature", stage=stage)
            return report

        # Pick next curriculum task round-robin by success count
        task = _CURRICULUM[self._successes % len(_CURRICULUM)]
        awareness = self.awareness(intent=f"build:{task['id']}")
        build = self.multi_pass_build(
            task["instruction"],
            task["test_code"],
            source=f"advanced_self_develop:{task['id']}",
            allow_reference=task.get("reference"),
        )
        # Soft continuous tick to fold curated rows into a learning proposal
        cont = None
        try:
            if (
                include_continuous_tick
                and build.get("curated")
                and hasattr(self.continuous, "tick_once")
            ):
                cont = self.continuous.tick_once()
        except Exception as exc:
            cont = {"ok": False, "error": str(exc)}

        out = {
            "ok": bool(build.get("ok")),
            "ran": True,
            "task_id": task["id"],
            "stage": stage,
            "build": {
                "solved": build.get("solved"),
                "curated": build.get("curated"),
                "origin": build.get("origin"),
                "passes": build.get("passes"),
            },
            "continuous": cont,
            "maturity": self.maturity(),
            "awareness": awareness,
            "weight_promotion": "never_auto",
            "precision": {
                "review_passes": self.review_passes,
                "max_repairs": self.max_repairs,
                "accept_only_verified": True,
            },
        }
        self._journal("autonomous_cycle", task=task["id"], ok=out["ok"], stage=stage)
        return out

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "maturity": self.maturity(),
            "awareness": self.awareness(intent="status"),
            "curriculum_size": len(_CURRICULUM),
            "review_passes": self.review_passes,
            "max_repairs": self.max_repairs,
            "weight_promotion": "never_auto",
        }
