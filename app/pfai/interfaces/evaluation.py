"""Evaluation suite contracts — extend EvaluationLab later without replacing it."""
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
    meta: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class EvaluationSuiteProtocol(Protocol):
    def run_suite(self, suite: str = "default") -> EvalReport:
        ...

    def list_suites(self) -> list[str]:
        ...
