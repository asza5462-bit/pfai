"""Evaluation + version-comparison contracts (wrap EvaluationLab later)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class EvalCase:
    case_id: str
    name: str
    input: Any = None
    expected: Any = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalReport:
    suite: str
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    cases: list[dict[str, Any]] = field(default_factory=list)
    ok: bool = True
    fingerprint: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class VersionCompareReport:
    """Compare candidate vs baseline before adopting a change."""

    baseline_id: str
    candidate_id: str
    baseline_score: float = 0.0
    candidate_score: float = 0.0
    regressions: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    ok_to_promote: bool = False
    requires_owner: bool = True
    details: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class EvaluationSuiteProtocol(Protocol):
    def run_suite(self, suite: str = "default") -> EvalReport:
        ...

    def list_suites(self) -> list[str]:
        ...


@runtime_checkable
class VersionComparisonProtocol(Protocol):
    def compare(self, baseline_id: str, candidate_id: str, *, suite: str = "regression") -> VersionCompareReport:
        ...
