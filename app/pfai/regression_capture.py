"""Turn confirmed bug fixes into durable regression tests.

Deliberately NOT automatic end-to-end: this module can queue a candidate
regression case and prove (via ground-truth sandboxed execution) that it is a
*real* regression -- the "broken" version actually fails the test and the
"fixed" version actually passes it. But it never writes into the live
tests/ directory by itself.

That boundary is intentional, not an oversight: a pipeline that both writes
its own test suite AND is graded by that same test suite is exactly the kind
of setup that can silently "fix" failures by weakening the tests instead of
the code. So capture() only queues a proven case to
data/regression_queue/pending.jsonl; a human calls materialize() explicitly
(mirroring LearningLoop.approve / ContinuousLearningOrchestrator.approve) to
actually add it to the tests/ directory PFAI's own promotion gate runs.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
import hashlib
import json

from .code_execution_evaluator import SandboxedCodeEvaluator


@dataclass(frozen=True)
class RegressionCase:
    case_id: str
    title: str
    broken_code: str
    fixed_code: str
    test_code: str
    created_at: str
    status: str = 'pending'  # pending | materialized | rejected


class RegressionCapture:
    def __init__(self, root='data/regression_queue', evaluator: Optional[SandboxedCodeEvaluator] = None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.queue_path = self.root / 'pending.jsonl'
        self.evaluator = evaluator or SandboxedCodeEvaluator()

    @staticmethod
    def _case_id(title: str, fixed_code: str) -> str:
        return hashlib.sha256((title + '\n' + fixed_code).encode('utf-8')).hexdigest()[:16]

    def capture(self, title: str, broken_code: str, fixed_code: str, test_code: str) -> dict:
        """Verify this is a genuine regression (broken fails, fixed passes)
        before queuing anything. Fails closed -- refuses to queue anything it
        cannot verify, rather than trusting the caller's labels."""
        broken_result = self.evaluator.evaluate(broken_code, test_code)
        if broken_result.passed:
            return {'queued': False, 'reason': "'broken' version did not actually fail the test -- not a real regression case"}

        fixed_result = self.evaluator.evaluate(fixed_code, test_code)
        if not fixed_result.passed:
            return {'queued': False, 'reason': f"'fixed' version still fails: {fixed_result.reason}"}

        case = RegressionCase(
            case_id=self._case_id(title, fixed_code),
            title=title,
            broken_code=broken_code,
            fixed_code=fixed_code,
            test_code=test_code,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        with self.queue_path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(asdict(case), ensure_ascii=False) + '\n')
        return {'queued': True, 'case_id': case.case_id}

    def pending(self) -> List[dict]:
        if not self.queue_path.exists():
            return []
        rows = [json.loads(l) for l in self.queue_path.read_text(encoding='utf-8').splitlines() if l.strip()]
        return [r for r in rows if r.get('status') == 'pending']

    def materialize(self, case_id: str, tests_dir='tests') -> dict:
        """Human-gated step: write ONE queued, already-verified case out as a
        real unittest file under tests_dir. Caller (a human operator, e.g. via
        an owner-authenticated API route) decides when this happens -- nothing
        in the automated 24/7 cycle calls this on its own."""
        rows = self.pending()
        case = next((r for r in rows if r['case_id'] == case_id), None)
        if case is None:
            return {'materialized': False, 'reason': 'case not found or already handled'}

        tests_path = Path(tests_dir)
        tests_path.mkdir(parents=True, exist_ok=True)
        out_path = tests_path / f"test_regression_{case['case_id']}.py"
        content = (
            f"# Auto-generated regression test -- human-approved via RegressionCapture.materialize().\n"
            f"# Title: {case['title']}\n"
            "import unittest\n\n"
            f"class TestRegression_{case['case_id']}(unittest.TestCase):\n"
            f"    def test_fix_holds(self):\n"
            f"        namespace = {{}}\n"
            f"        exec({case['fixed_code']!r}, namespace)\n"
            f"        exec({case['test_code']!r}, namespace)\n\n"
            "if __name__ == '__main__':\n    unittest.main()\n"
        )
        out_path.write_text(content, encoding='utf-8')
        self._update_status(case_id, 'materialized')
        return {'materialized': True, 'path': str(out_path)}

    def reject(self, case_id: str) -> dict:
        self._update_status(case_id, 'rejected')
        return {'rejected': True}

    def _update_status(self, case_id: str, status: str) -> None:
        if not self.queue_path.exists():
            return
        rows = [json.loads(l) for l in self.queue_path.read_text(encoding='utf-8').splitlines() if l.strip()]
        for r in rows:
            if r['case_id'] == case_id:
                r['status'] = status
        with self.queue_path.open('w', encoding='utf-8') as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
