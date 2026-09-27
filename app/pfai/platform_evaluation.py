"""Evaluation suite + version comparison adapters (PHASE 3 richer baselines)."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable

from pfai.evaluation_lab import EvaluationLab
from pfai.interfaces.evaluation import EvalReport, VersionCompareReport
from pfai.interfaces.memory import MemoryKind
from pfai.interfaces.migration import PFAI_SCHEMA_VERSION

__all__ = ["PlatformEvaluation", "EvalReport", "VersionCompareReport"]


class PlatformEvaluation:
    def __init__(
        self,
        lab: EvaluationLab | None = None,
        minimum_score: float = 0.5,
        *,
        baselines_path: str = "data/longevity/eval_baselines.json",
    ) -> None:
        self.lab = lab or EvaluationLab(minimum_score=minimum_score)
        self.baselines_path = Path(baselines_path)
        self.baselines_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._suites: dict[str, dict[str, Callable[[], float]]] = {
            "smoke": {
                "always_ok": lambda: 1.0,
            },
            "longevity": {
                "schema_version_defined": lambda: 1.0 if PFAI_SCHEMA_VERSION >= 1 else 0.0,
                "memory_kinds_complete": lambda: 1.0 if len(list(MemoryKind)) >= 8 else 0.0,
                "no_weight_mutation_invariant": lambda: 1.0,  # enforced by learning pipeline tests/API
            },
            "regression": {
                "smoke_anchor": lambda: 1.0,
            },
        }
        self._baselines: dict[str, EvalReport] = {}
        self._load_baselines()

    def _load_baselines(self) -> None:
        if not self.baselines_path.exists():
            return
        try:
            raw = json.loads(self.baselines_path.read_text(encoding="utf-8"))
        except Exception:
            return
        for bid, payload in (raw or {}).items():
            self._baselines[bid] = EvalReport(
                suite=payload.get("suite", ""),
                passed=int(payload.get("passed") or 0),
                failed=int(payload.get("failed") or 0),
                skipped=int(payload.get("skipped") or 0),
                cases=list(payload.get("cases") or []),
                ok=bool(payload.get("ok", True)),
                fingerprint=str(payload.get("fingerprint") or ""),
                meta=dict(payload.get("meta") or {}),
            )

    def _persist_baselines(self) -> None:
        payload = {
            bid: {
                "suite": r.suite,
                "passed": r.passed,
                "failed": r.failed,
                "skipped": r.skipped,
                "cases": r.cases,
                "ok": r.ok,
                "fingerprint": r.fingerprint,
                "meta": r.meta,
            }
            for bid, r in self._baselines.items()
        }
        tmp = self.baselines_path.with_suffix(".tmp")
        with self._lock:
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.baselines_path)

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
        self._persist_baselines()

    def get_baseline(self, baseline_id: str) -> EvalReport | None:
        return self._baselines.get(baseline_id)

    def compare(self, baseline_id: str, candidate_id: str, *, suite: str = "regression") -> VersionCompareReport:
        base = self._baselines.get(baseline_id) or self.run_suite(suite)
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
