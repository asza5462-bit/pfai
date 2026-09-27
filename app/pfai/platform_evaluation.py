"""Evaluation suite + version comparison adapters (PHASE 2)."""
from __future__ import annotations

from typing import Any, Callable

from pfai.evaluation_lab import EvaluationLab
from pfai.interfaces.evaluation import EvalReport, VersionCompareReport

__all__ = ["PlatformEvaluation", "EvalReport", "VersionCompareReport"]


class PlatformEvaluation:
    def __init__(self, lab: EvaluationLab | None = None, minimum_score: float = 0.5) -> None:
        self.lab = lab or EvaluationLab(minimum_score=minimum_score)
        self._suites: dict[str, dict[str, Callable[[], float]]] = {
            "smoke": {
                "always_ok": lambda: 1.0,
            }
        }
        self._baselines: dict[str, EvalReport] = {}

    def register_suite(self, name: str, suites: dict[str, Callable[[], float]]) -> None:
        self._suites[name] = suites

    def list_suites(self) -> list[str]:
        return sorted(self._suites.keys())

    def run_suite(self, suite: str = "default") -> EvalReport:
        name = suite if suite in self._suites else ("smoke" if suite == "default" else suite)
        if name not in self._suites:
            return EvalReport(suite=suite, ok=False, failed=1, cases=[{"error": "unknown suite"}])
        raw = self.lab.evaluate(self._suites[name])
        passed = sum(1 for r in raw["results"] if r["passed"])
        failed = sum(1 for r in raw["results"] if not r["passed"])
        report = EvalReport(
            suite=name,
            passed=passed,
            failed=failed,
            ok=bool(raw.get("passed")),
            fingerprint=str(raw.get("fingerprint") or ""),
            cases=list(raw.get("results") or []),
            meta={"overall": raw.get("overall")},
        )
        return report

    def record_baseline(self, baseline_id: str, report: EvalReport) -> None:
        self._baselines[baseline_id] = report

    def compare(self, baseline_id: str, candidate_id: str, *, suite: str = "regression") -> VersionCompareReport:
        base = self._baselines.get(baseline_id) or self.run_suite(suite)
        # candidate_id may be another stored baseline or a fresh run tagged by id
        cand = self._baselines.get(candidate_id) or self.run_suite(suite)
        base_score = float((base.meta or {}).get("overall") or (base.passed / max(1, base.passed + base.failed)))
        cand_score = float((cand.meta or {}).get("overall") or (cand.passed / max(1, cand.passed + cand.failed)))
        regressions = []
        improvements = []
        base_cases = {c.get("name"): c for c in base.cases if isinstance(c, dict)}
        for c in cand.cases:
            if not isinstance(c, dict):
                continue
            name = c.get("name")
            prev = base_cases.get(name)
            if prev and prev.get("passed") and not c.get("passed"):
                regressions.append(str(name))
            if prev and (not prev.get("passed")) and c.get("passed"):
                improvements.append(str(name))
        ok = cand_score >= base_score and not regressions
        return VersionCompareReport(
            baseline_id=baseline_id,
            candidate_id=candidate_id,
            baseline_score=base_score,
            candidate_score=cand_score,
            regressions=regressions,
            improvements=improvements,
            ok_to_promote=ok,
            requires_owner=True,
            details={"suite": suite},
        )
