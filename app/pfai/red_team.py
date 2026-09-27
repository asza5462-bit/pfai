from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Iterable
import hashlib, json

@dataclass(frozen=True)
class AttackCase:
    case_id: str
    category: str
    prompt: str
    expected: str = ""
    metadata: dict | None = None

@dataclass(frozen=True)
class AttackResult:
    case_id: str
    category: str
    passed: bool
    response: str
    reason: str = ""
    severity: str = "medium"
    fingerprint: str = ""

class RedTeamLab:
    """Deterministic adversarial test harness; no network or privileged execution."""
    CATEGORIES = ("prompt_injection", "tool_boundary", "data_poisoning", "code_safety", "regression")
    SEVERITY = {"low", "medium", "high", "critical"}

    def __init__(self, max_cases: int = 100, max_response: int = 12000):
        if max_cases <= 0 or max_response <= 0:
            raise ValueError("limits must be positive")
        self.max_cases, self.max_response = int(max_cases), int(max_response)

    @staticmethod
    def fingerprint(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def build_cases(self, cases: Iterable[AttackCase]) -> list[AttackCase]:
        out, seen = [], set()
        for c in cases:
            if c.category not in self.CATEGORIES:
                continue
            if c.case_id in seen:
                continue
            if not c.prompt.strip():
                continue
            out.append(c); seen.add(c.case_id)
            if len(out) >= self.max_cases:
                break
        return out

    def run(self, cases: Iterable[AttackCase], responder: Callable[[AttackCase], str],
            judge: Callable[[AttackCase, str], tuple[bool, str]] | None = None) -> list[AttackResult]:
        results = []
        for case in self.build_cases(cases):
            try:
                response = str(responder(case))[:self.max_response]
                if judge:
                    passed, reason = judge(case, response)
                else:
                    # Default judge: expected marker must occur when supplied.
                    passed = (not case.expected) or (case.expected in response)
                    reason = "expected_marker" if case.expected else "no_judge"
                severity = str((case.metadata or {}).get("severity", "medium"))
                if severity not in self.SEVERITY: severity = "medium"
            except Exception as exc:
                response, passed, reason, severity = "", False, f"responder_error:{type(exc).__name__}", "high"
            fp = self.fingerprint(case.case_id + "\n" + response)
            results.append(AttackResult(case.case_id, case.category, bool(passed), response, reason, severity, fp))
        return results

    @staticmethod
    def regression_cases(results: Iterable[AttackResult]) -> list[dict]:
        return [{"case_id": r.case_id, "category": r.category, "severity": r.severity,
                 "fingerprint": r.fingerprint, "expected_pass": False if not r.passed else True}
                for r in results]

    @staticmethod
    def summary(results: Iterable[AttackResult]) -> dict:
        rows=list(results)
        return {"total": len(rows), "passed": sum(r.passed for r in rows),
                "failed": sum(not r.passed for r in rows),
                "high_or_critical_failures": sum((not r.passed) and r.severity in {"high","critical"} for r in rows)}

    def export_regression(self, results: Iterable[AttackResult], path: str) -> dict:
        rows=self.regression_cases(results)
        with open(path, "w", encoding="utf-8") as f:
            for row in rows: f.write(json.dumps(row, ensure_ascii=False)+"\n")
        return {"path": path, "count": len(rows), "fingerprint": self.fingerprint("\n".join(r["fingerprint"] for r in rows))}
