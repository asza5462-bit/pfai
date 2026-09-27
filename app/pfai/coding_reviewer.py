"""Specialized code review — explains issues; does not silently rewrite without teaching."""
from __future__ import annotations

import ast
import re
from typing import Any

from .code_evaluation import PythonCodeEvaluator


class CodingReviewer:
    def __init__(self, static: PythonCodeEvaluator | None = None):
        self.static = static or PythonCodeEvaluator()

    def review(self, code: str, language: str = "python", context: str = "") -> dict[str, Any]:
        language = (language or "python").lower()
        findings = []
        if language in {"python", "py"}:
            findings.extend(self._review_python(code or ""))
        else:
            findings.append({
                "severity": "info",
                "category": "language",
                "message": f"Executable deep review currently strongest for Python; provided static/heuristic notes for {language}.",
                "suggestion": "Describe intent and constraints; request architecture review if needed.",
            })
            if "password" in (code or "").lower() or "api_key" in (code or "").lower():
                findings.append({
                    "severity": "high",
                    "category": "security",
                    "message": "Possible secret/credential literal detected in source.",
                    "suggestion": "Move secrets to environment/secret store; never commit them.",
                })
        summary = {
            "correctness": _score_category(findings, "correctness"),
            "readability": _score_category(findings, "readability"),
            "security": _score_category(findings, "security"),
            "maintainability": _score_category(findings, "maintainability"),
            "testing": _score_category(findings, "testing"),
            "performance": _score_category(findings, "performance"),
        }
        return {
            "ok": True,
            "language": language,
            "findings": findings,
            "summary": summary,
            "tested": False,
            "note": "Review is static/heuristic unless paired with sandbox tests.",
            "context_used": bool(context.strip()),
        }

    def _review_python(self, code: str) -> list[dict]:
        findings = []
        static = self.static.evaluate(code)
        if not static.syntax_ok:
            findings.append({
                "severity": "high",
                "category": "correctness",
                "message": f"Syntax error: {static.details.get('error')}",
                "suggestion": "Fix syntax before optimizing or refactoring.",
            })
            return findings
        if static.unsafe_imports:
            findings.append({
                "severity": "high",
                "category": "security",
                "message": f"Blocked/unsafe imports: {', '.join(static.unsafe_imports)}",
                "suggestion": "Remove dangerous imports; keep learner/sandbox code dependency-light.",
            })
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return findings
        functions = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if not functions and code.strip():
            findings.append({
                "severity": "medium",
                "category": "maintainability",
                "message": "Top-level script with no functions.",
                "suggestion": "Wrap logic in named functions for testability.",
            })
        for fn in functions:
            if not ast.get_docstring(fn):
                findings.append({
                    "severity": "low",
                    "category": "readability",
                    "message": f"Function `{fn.name}` has no docstring.",
                    "suggestion": "Add a one-line docstring describing inputs/outputs.",
                })
            if len(fn.body) > 40:
                findings.append({
                    "severity": "medium",
                    "category": "maintainability",
                    "message": f"Function `{fn.name}` is long ({len(fn.body)} body stmts).",
                    "suggestion": "Split into smaller helpers.",
                })
        if "except:" in code or re.search(r"except\s*:", code):
            findings.append({
                "severity": "medium",
                "category": "correctness",
                "message": "Bare except detected.",
                "suggestion": "Catch specific exceptions and handle/log them.",
            })
        if "TODO" in code or "pass" in code:
            findings.append({
                "severity": "info",
                "category": "testing",
                "message": "Incomplete placeholders (TODO/pass) present.",
                "suggestion": "Finish implementation and add assertions/tests.",
            })
        if not findings:
            findings.append({
                "severity": "info",
                "category": "correctness",
                "message": "No major static issues found.",
                "suggestion": "Run sandbox tests to verify behavior before claiming correctness.",
            })
        return findings


def _score_category(findings: list[dict], category: str) -> float:
    relevant = [f for f in findings if f.get("category") == category]
    if not relevant:
        return 0.8
    penalty = 0.0
    for f in relevant:
        sev = f.get("severity")
        penalty += {"high": 0.35, "medium": 0.2, "low": 0.1, "info": 0.02}.get(sev, 0.1)
    return round(max(0.0, 1.0 - penalty), 2)
