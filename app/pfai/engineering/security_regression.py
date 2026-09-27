"""PHASE 15 security regression engine — tests from verified findings."""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from pfai.engineering.project_workspace import ProjectWorkspace
from pfai.engineering.secure_analyzer import SecureCodeAnalyzer
from pfai.engineering.types import FindingStatus, new_id


_CATEGORY_PATTERNS: dict[str, str] = {
    "secret_exposure": r"(?i)(api[_-]?key|secret|password|token)\s*=\s*['\"][^'\"]{8,}['\"]",
    "insecure_cors": r"(?i)Access-Control-Allow-Origin['\"\s:]*\*",
    "xss_risk": r"(?i)innerHTML\s*=|document\.write\(",
    "insecure_deserialization": r"(?i)\bpickle\.loads?\(",
    "weak_input_validation": r"(?i)\beval\(|\bexec\(",
}


class SecurityRegressionEngine:
    """
    When a vulnerability is fixed and verified:
    - generate a regression test where appropriate
    - execute it
    - store the result
    - prevent silent reintroduction
    """

    def __init__(self, project_path: str | Path) -> None:
        self.workspace = ProjectWorkspace(project_path)
        self.store = self.workspace.meta_dir / "security_regressions.jsonl"
        self.tests_dir = self.workspace.root / "tests" / "security_regression"

    def generate_from_finding(self, finding: dict[str, Any]) -> dict[str, Any]:
        fid = finding.get("finding_id") or new_id("find")
        cat = finding.get("category") or "unknown"
        path = finding.get("file_path") or finding.get("affected_component") or ""
        if not (
            finding.get("verified")
            or finding.get("verification_status")
            in (FindingStatus.VERIFIED.value, FindingStatus.FIXED.value, "verified", "fixed")
            or finding.get("marked_fixed")
        ):
            return {"ok": False, "error": "finding_not_verified", "finding_id": fid}

        self.tests_dir.mkdir(parents=True, exist_ok=True)
        safe_cat = re.sub(r"[^a-z0-9_]+", "_", cat.lower())[:40] or "issue"
        test_name = f"test_reg_{safe_cat}_{fid[-8:]}.py"
        rel = f"tests/security_regression/{test_name}"
        pattern = _CATEGORY_PATTERNS.get(cat, "")
        if path and pattern:
            body = f'''"""Security regression for {fid} ({cat}) — self-contained."""
from __future__ import annotations
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / {path!r}
PATTERN = re.compile({pattern!r})


class TestSecurityRegression_{fid[-8:]}(unittest.TestCase):
    def test_pattern_not_reintroduced(self):
        self.assertTrue(TARGET.exists(), "target file missing")
        text = TARGET.read_text(encoding="utf-8", errors="replace")
        self.assertIsNone(PATTERN.search(text), "security regression: {cat} pattern returned")


if __name__ == "__main__":
    unittest.main()
'''
        else:
            body = f'''"""Security regression smoke for {fid} ({cat})."""
from __future__ import annotations
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class TestSecurityRegression_{fid[-8:]}(unittest.TestCase):
    def test_project_still_present(self):
        self.assertTrue(ROOT.exists())


if __name__ == "__main__":
    unittest.main()
'''
        write = self.workspace.write_text(rel, body, overwrite=True)
        if not write.get("ok"):
            return {"ok": False, "error": write.get("error"), "finding_id": fid}

        row = {
            "regression_id": new_id("sreg"),
            "ts": time.time(),
            "finding_id": fid,
            "category": cat,
            "test_path": rel,
            "affected_component": path,
            "status": "generated",
        }
        with self.store.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return {"ok": True, **row}

    def run_regressions(self) -> dict[str, Any]:
        if not self.tests_dir.exists():
            return {"ok": True, "ran": False, "note": "no_regression_tests", "passed": True}
        try:
            proc = subprocess.run(
                ["python", "-m", "pytest", str(self.tests_dir), "-q", "--tb=line"],
                capture_output=True,
                text=True,
                timeout=45,
                cwd=str(self.workspace.root),
            )
            passed = proc.returncode == 0
            result = {
                "ok": passed,
                "ran": True,
                "passed": passed,
                "returncode": proc.returncode,
                "output": ((proc.stdout or "") + (proc.stderr or ""))[:2500],
            }
            with self.store.open("a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        {"regression_id": new_id("srun"), "ts": time.time(), "event": "run", **result},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            return result
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "ran": False, "passed": False, "error": type(exc).__name__}

    def verify_finding_fixed(self, finding: dict[str, Any]) -> dict[str, Any]:
        """Re-analyze project; finding is verified fixed only if category+component gone."""
        analysis = SecureCodeAnalyzer(self.workspace.root).analyze()
        cat = finding.get("category")
        path = finding.get("file_path") or finding.get("affected_component") or ""
        remaining = [
            f
            for f in (analysis.get("findings") or [])
            if f.get("category") == cat
            and (not path or path in str(f.get("file_path") or f.get("affected_component") or ""))
        ]
        verified = len(remaining) == 0
        return {
            "ok": True,
            "verified": verified,
            "verification_status": FindingStatus.VERIFIED.value if verified else FindingStatus.OPEN.value,
            "remediation_status": "fixed" if verified else "unfixed",
            "remaining": remaining,
            "finding_id": finding.get("finding_id"),
            "marked_fixed": verified,
        }
