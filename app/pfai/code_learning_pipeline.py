"""Closes the loop from "the agent writes code" to "PFAI learns from a verified
solution" end to end, ground-truth checked at every step, still fully
human-approval-gated before anything is ever promoted.

Flow:
  1. Ask the connected model for N candidate solutions to a coding instruction
     (each with a slightly different steer, so they aren't just N identical
     samples of the same completion).
  2. Run every candidate against caller-supplied test_code in the sandboxed
     executor via `code_best_of_n.select_best_solution` — ground truth from
     actually running the code, never a guess about whether it "looks right".
  3. Only if a candidate genuinely passes its tests is it curated into
     `ContinuousLearningOrchestrator` as one training example.

This module calls the model and the sandbox; it never promotes anything on its
own and never touches `require_human_approval` — a curated example here still
needs an explicit `orchestrator.run_cycle()` + `approve()` before it can ever
become active, exactly like any other curated example.
"""
from __future__ import annotations
from typing import List, Optional
import json

from .code_best_of_n import select_best_solution, BestOfNResult
from .code_execution_evaluator import SandboxedCodeEvaluator
from .continuous_learning_orchestrator import ContinuousLearningOrchestrator
from .research_gate import ResearchGate
from .code_autofix_engine import CodeAutoFixEngine, CodeAdversarialVerifier

_SOLVE_PROMPT = (
    "Write a single, complete Python solution to this instruction. Return ONLY the "
    "code, no prose, no markdown fences.\n\nInstruction: {instruction}\n{variation}"
    "{research_context}"
)

# Cheap, deterministic diversity across the N samples without needing a
# temperature knob every provider supports identically.
_VARIATIONS = (
    "",
    "Prefer a different valid approach than the most obvious one.",
    "Optimize for simplicity and readability above all else.",
    "Be careful about edge cases (empty input, zero, negative numbers).",
    "Write it as a single small, well-named function.",
)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


class CodeLearningPipeline:
    def __init__(self, model, orchestrator: ContinuousLearningOrchestrator,
                 evaluator: Optional[SandboxedCodeEvaluator] = None, n: int = 3,
                 research_gate: Optional[ResearchGate] = None, auto_repair: bool = True,
                 max_repairs: int = 4, adversarial_rounds: int = 2):
        if n <= 0:
            raise ValueError("n must be positive")
        self.model = model
        self.orchestrator = orchestrator
        self.evaluator = evaluator or SandboxedCodeEvaluator()
        self.n = int(n)
        # Optional and off by default: only set if the caller explicitly
        # constructs and passes a ResearchGate (see api.py / run_continuous.py
        # for how that stays behind security.allow_network + allowed_domains).
        self.research_gate = research_gate
        self.auto_repair = bool(auto_repair)
        self.auto_fixer = CodeAutoFixEngine(model, self.evaluator, max_repairs=max_repairs) if self.auto_repair else None
        self.adversarial = CodeAdversarialVerifier(model, self.evaluator, rounds=adversarial_rounds) if adversarial_rounds > 0 else None

    def _generate_candidates(self, instruction: str, research_context: str = "") -> List[str]:
        candidates = []
        ctx = f"\n\n{research_context}\n" if research_context else ""
        for i in range(self.n):
            variation = _VARIATIONS[i % len(_VARIATIONS)]
            try:
                raw = self.model.generate(_SOLVE_PROMPT.format(
                    instruction=instruction, variation=variation, research_context=ctx))
            except Exception:
                continue  # one bad generation should not sink the whole batch
            code = _strip_fences(raw)
            if code:
                candidates.append(code)
        return candidates

    def solve_and_learn(self, instruction: str, test_code: str,
                         source: str = "code_learning_pipeline",
                         reference_urls: Optional[List[str]] = None,
                         task_id: str = "") -> dict:
        """Generate candidates, keep only the ground-truth-verified winner (if any),
        and curate it as a training example. Never learns from a candidate that
        didn't actually pass its tests; never promotes anything by itself.

        reference_urls is entirely optional. If given and a ResearchGate was
        configured, up to a few of those URLs are fetched through the same
        policy gate as everything else in this codebase (off by default,
        allowlist-only) and given to the model as clearly-labeled, inert
        reference context -- never as instructions. Every fetch, allowed or
        denied, is recorded to a tamper-evident ledger, and the exact sources
        (with content hashes) are attached to the curated example's metadata
        so a human approver can see what, if anything, informed it."""
        if not instruction.strip() or not test_code.strip():
            return {"solved": False, "reason": "instruction and test_code are both required", "curated": False}

        sources = []
        research_context = ""
        if reference_urls and self.research_gate is not None:
            sources = self.research_gate.gather(reference_urls, task_id=task_id or source)
            research_context = self.research_gate.format_context(sources)

        candidates = self._generate_candidates(instruction, research_context)
        if not candidates:
            return {"solved": False, "reason": "model produced no usable candidates",
                     "attempts": 0, "curated": False}

        result: BestOfNResult = select_best_solution(candidates, test_code, evaluator=self.evaluator)
        repair_result = None
        if result.best_code is None and self.auto_fixer:
            # Pick the shortest candidate as the repair seed; it is only a seed,
            # never treated as correct until the repair loop executes the tests.
            seed = min(candidates, key=len)
            repair_result = self.auto_fixer.solve_and_repair(instruction, seed, test_code)
            if repair_result.solved:
                result_code = repair_result.code
                attempts = len(candidates) + repair_result.attempts
            else:
                return {"solved": False, "reason": "no candidate passed and bounded auto-repair could not verify a fix",
                        "attempts": len(candidates) + repair_result.attempts, "curated": False,
                        "repair_history": repair_result.history}
        else:
            result_code = result.best_code
            attempts = len(candidates)

        metadata = {}
        if repair_result is not None:
            metadata["auto_repair"] = {"repairs": repair_result.repairs, "history": repair_result.history,
                                        "regression_added": repair_result.regression_added}

        # Second verification layer: generate independent edge-case tests.
        # A passing candidate is never trusted solely because the caller's tests
        # are green. If an adversarial suite exposes a defect, bounded repair is
        # attempted against the combined test contract.
        adversarial_tests = []
        if self.adversarial is not None:
            adversarial_tests = self.adversarial.generate(instruction, result_code, test_code)
            for extra in adversarial_tests:
                check = self.evaluator.evaluate(result_code, extra)
                if not check.passed and self.auto_fixer:
                    combined = test_code + "\n" + extra
                    repaired = self.auto_fixer.solve_and_repair(instruction, result_code, combined)
                    if not repaired.solved:
                        return {"solved": False, "reason": "adversarial verification found an unrepairable defect",
                                "attempts": attempts + repaired.attempts, "curated": False,
                                "repair_history": repaired.history}
                    result_code = repaired.code
                    repair_result = repaired

        metadata["verification"] = {"official_tests": True, "adversarial_rounds": len(adversarial_tests),
                                     "adversarial_tests_passed": len(adversarial_tests)}
        if sources:
            metadata["research"] = ResearchGate.provenance(sources)
        curation = self.orchestrator.register_batch([{
            "instruction": instruction,
            "response": result_code,
            "source": source,
            "track": "software_engineering",
            "metadata": metadata,
        }])
        return {
            "solved": True,
            "code": result_code,
            "attempts": attempts,
            "passing_candidates": len(result.passing_indices),
            "curated": curation.get("accepted", 0) > 0,
            "curation": curation,
            "research": ResearchGate.provenance(sources) if sources else [],
        }

    def generate_and_learn_task(self, source: str = "autonomous_code_curriculum") -> dict:
        """Generate a coding task and tests, then solve through verified repair."""
        prompt = (
            "Create ONE difficult but self-contained Python coding exercise for a "
            "software-engineering training curriculum. Return ONLY JSON with keys "
            "instruction and test_code. The test_code must contain assert statements, "
            "must not redefine the requested function/class, and must use no I/O, "
            "network, filesystem, subprocess, eval, exec, reflection, or randomness. "
            "Cover edge cases and at least one non-obvious case."
        )
        try:
            raw = self.model.generate(prompt)
            a, b = raw.find("{"), raw.rfind("}")
            obj = json.loads(raw[a:b+1]) if a >= 0 and b > a else None
            if not isinstance(obj, dict):
                return {"solved": False, "reason": "teacher returned invalid task JSON"}
            instruction = str(obj.get("instruction", "")).strip()
            tests = str(obj.get("test_code", "")).strip()
            if not instruction or not tests or "assert" not in tests:
                return {"solved": False, "reason": "teacher task missing instruction/tests"}
            return self.solve_and_learn(instruction, tests, source=source)
        except Exception as exc:
            return {"solved": False, "reason": f"task generation failed: {type(exc).__name__}"}
