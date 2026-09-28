"""PHASE 19 Algorithm Intelligence — structured analysis; never fabricates benchmarks."""
from __future__ import annotations

import ast
import re
import time
from typing import Any

from pfai.elite.types import new_id


# Known patterns with honest complexity statements (textbook, not measured)
_KNOWN: list[dict[str, Any]] = [
    {
        "id": "bubble_sort",
        "patterns": (r"bubble\s*sort", r"for .+ in range\(len.+\):\s*\n\s*for .+ in range"),
        "name": "Bubble Sort",
        "time_complexity": "O(n^2)",
        "space_complexity": "O(1)",
        "edge_cases": ["empty list", "single element", "already sorted", "reverse sorted", "duplicates"],
        "optimization_hints": ["early-exit if no swaps", "prefer O(n log n) sorts for large n"],
    },
    {
        "id": "binary_search",
        "patterns": (r"binary\s*search", r"lo\s*,\s*hi", r"mid\s*=\s*.*//\s*2"),
        "name": "Binary Search",
        "time_complexity": "O(log n)",
        "space_complexity": "O(1)",
        "edge_cases": ["empty array", "target missing", "duplicates", "unsorted input (invalid precondition)"],
        "optimization_hints": ["ensure sorted precondition", "watch overflow on mid calculation"],
    },
    {
        "id": "dfs_bfs",
        "patterns": (r"\bdfs\b", r"\bbfs\b", r"depth[- ]first", r"breadth[- ]first"),
        "name": "Graph Search (DFS/BFS)",
        "time_complexity": "O(V+E)",
        "space_complexity": "O(V)",
        "edge_cases": ["disconnected graph", "cycles", "single node", "missing neighbors"],
        "optimization_hints": ["visited set required", "BFS for shortest unweighted path"],
    },
    {
        "id": "dynamic_programming",
        "patterns": (r"dynamic\s*programming", r"\bdp\[", r"memoiz"),
        "name": "Dynamic Programming",
        "time_complexity": "problem-dependent (often O(n*states))",
        "space_complexity": "problem-dependent",
        "edge_cases": ["base cases", "overlapping subproblems absent", "integer overflow"],
        "optimization_hints": ["rolling arrays for space", "verify recurrence correctness"],
    },
    {
        "id": "two_pointers",
        "patterns": (r"two\s*pointer", r"left\s*.*\s*right"),
        "name": "Two Pointers",
        "time_complexity": "often O(n)",
        "space_complexity": "O(1)",
        "edge_cases": ["empty", "all equal", "no valid pair"],
        "optimization_hints": ["sorted input often required"],
    },
]


_OPTIMIZED_TEMPLATES: dict[str, str] = {
    "bubble_sort": '''def sort_optimized(items: list) -> list:
    """Timsort via built-in sorted — O(n log n) typical; do not claim fabricated benchmarks."""
    return sorted(items)


def test_sort_optimized():
    assert sort_optimized([]) == []
    assert sort_optimized([1]) == [1]
    assert sort_optimized([3, 1, 2]) == [1, 2, 3]
    assert sort_optimized([2, 2, 1]) == [1, 2, 2]
''',
    "binary_search": '''def binary_search(arr: list, target) -> int:
    """Iterative binary search. Returns index or -1. Requires sorted arr."""
    lo, hi = 0, len(arr) - 1
    while lo <= hi:
        mid = lo + (hi - lo) // 2
        if arr[mid] == target:
            return mid
        if arr[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1


def test_binary_search():
    assert binary_search([], 1) == -1
    assert binary_search([1], 1) == 0
    assert binary_search([1, 3, 5, 7], 5) == 2
    assert binary_search([1, 3, 5, 7], 2) == -1
''',
}


class AlgorithmIntelligence:
    """
    Algorithm identification, complexity reasoning, edge cases, optional optimized
    implementation + real local tests. Never fabricates benchmark timings.
    """

    VERSION = "19.0.0"

    def analyze(self, text: str = "", *, code: str = "") -> dict[str, Any]:
        started = time.time()
        blob = f"{text}\n{code}"
        matches = []
        for spec in _KNOWN:
            for pat in spec["patterns"]:
                if re.search(pat, blob, re.I | re.M):
                    matches.append(spec)
                    break
        identified = matches[0] if matches else None
        ast_notes = self._ast_notes(code) if code.strip() else {}

        if not identified and not code.strip() and not any(
            w in (text or "").lower() for w in ("algorithm", "complexity", "big-o", "big o", "o(n")
        ):
            return {
                "ok": True,
                "identified": False,
                "note": "no_algorithm_pattern_detected",
                "fabricated_benchmarks": False,
                "duration_seconds": time.time() - started,
            }

        analysis = {
            "analysis_id": new_id("algo"),
            "identified": bool(identified),
            "algorithm_id": (identified or {}).get("id"),
            "name": (identified or {}).get("name") or "unclassified",
            "time_complexity": (identified or {}).get("time_complexity") or "unknown_without_more_context",
            "space_complexity": (identified or {}).get("space_complexity") or "unknown_without_more_context",
            "edge_cases": list((identified or {}).get("edge_cases") or ["empty input", "single element", "duplicates"]),
            "optimization_hints": list((identified or {}).get("optimization_hints") or []),
            "correctness_notes": [
                "Complexity statements are asymptotic textbook classifications, not measured runtimes.",
                "No fabricated benchmark numbers are produced.",
            ],
            "ast": ast_notes,
            "alternatives": self._alternatives(identified),
            "fabricated_benchmarks": False,
            "version": self.VERSION,
            "duration_seconds": time.time() - started,
        }
        return {"ok": True, **analysis}

    def _ast_notes(self, code: str) -> dict[str, Any]:
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return {"ok": False, "error": "syntax_error", "detail": str(exc)[:200]}
        loops = sum(isinstance(n, (ast.For, ast.While)) for n in ast.walk(tree))
        nested = 0
        for n in ast.walk(tree):
            if isinstance(n, (ast.For, ast.While)):
                nested = max(
                    nested,
                    sum(isinstance(c, (ast.For, ast.While)) for c in ast.walk(n)) - 1,
                )
        return {"ok": True, "loop_count": loops, "max_extra_nested_loops": nested}

    def _alternatives(self, identified: dict[str, Any] | None) -> list[dict[str, str]]:
        if not identified:
            return []
        aid = identified.get("id")
        if aid == "bubble_sort":
            return [
                {"name": "Timsort / sorted()", "time_complexity": "O(n log n)", "note": "preferred general-purpose"},
                {"name": "Heap sort", "time_complexity": "O(n log n)", "note": "guaranteed bound"},
            ]
        if aid == "binary_search":
            return [{"name": "bisect module", "time_complexity": "O(log n)", "note": "stdlib"}]
        return []

    def implement_optimized(self, analysis: dict[str, Any]) -> dict[str, Any]:
        aid = analysis.get("algorithm_id")
        template = _OPTIMIZED_TEMPLATES.get(aid or "")
        if not template:
            return {
                "ok": False,
                "error": "no_safe_optimized_template",
                "note": "Will not invent an optimized implementation without a verified template",
                "fabricated_benchmarks": False,
            }
        return {
            "ok": True,
            "algorithm_id": aid,
            "code": template,
            "tests_embedded": True,
            "fabricated_benchmarks": False,
            "claim": "Implementation provided; complexity is textbook classification only",
        }

    def run_embedded_tests(self, code: str) -> dict[str, Any]:
        """Execute embedded test_* functions in a restricted namespace — real run, no fake pass."""
        ns: dict[str, Any] = {}
        try:
            exec(compile(code, "<algo_opt>", "exec"), ns, ns)  # noqa: S102 — bounded generated template only
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": type(exc).__name__, "detail": str(exc)[:300], "ran": False}
        tests = [name for name, obj in ns.items() if name.startswith("test_") and callable(obj)]
        failures = []
        for name in tests:
            try:
                ns[name]()
            except Exception as exc:  # noqa: BLE001
                failures.append({"test": name, "error": type(exc).__name__, "detail": str(exc)[:200]})
        return {
            "ok": not failures,
            "ran": True,
            "tests_executed": tests,
            "failures": failures,
            "fabricated": False,
        }

    def full_pipeline(self, message: str, *, code: str = "", implement: bool = True) -> dict[str, Any]:
        analysis = self.analyze(message, code=code)
        stages = [{"stage": "analyze", "ok": analysis.get("ok")}]
        implementation = None
        test_result = None
        if implement and analysis.get("identified"):
            implementation = self.implement_optimized(analysis)
            stages.append({"stage": "implement_optimized", "ok": implementation.get("ok")})
            if implementation.get("ok") and implementation.get("code"):
                test_result = self.run_embedded_tests(implementation["code"])
                stages.append({"stage": "test", "ok": test_result.get("ok"), "ran": test_result.get("ran")})
        return {
            "ok": bool(analysis.get("ok")) and (test_result is None or test_result.get("ok")),
            "analysis": analysis,
            "implementation": implementation,
            "test_result": test_result,
            "stages": stages,
            "fabricated_benchmarks": False,
            "explanation": self._explain(analysis, implementation, test_result),
        }

    def _explain(self, analysis: dict, implementation: dict | None, test_result: dict | None) -> str:
        parts = [
            f"Algorithm: {analysis.get('name')}",
            f"Time: {analysis.get('time_complexity')}",
            f"Space: {analysis.get('space_complexity')}",
            f"Edge cases: {', '.join(analysis.get('edge_cases') or [])}",
        ]
        if implementation and implementation.get("ok"):
            parts.append("Optimized implementation generated from verified template.")
        if test_result and test_result.get("ran"):
            parts.append(
                "Tests "
                + ("passed" if test_result.get("ok") else f"failed:{test_result.get('failures')}")
            )
        parts.append("No fabricated benchmark timings.")
        return " ".join(parts)
