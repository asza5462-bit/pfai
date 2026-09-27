from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional
import ast, hashlib, json, subprocess, sys, tempfile

@dataclass(frozen=True)
class SyntheticTask:
    task_id: str
    instruction: str
    track: str = 'software_engineering'
    difficulty: int = 1
    metadata: dict | None = None

@dataclass(frozen=True)
class Candidate:
    task_id: str
    response: str
    candidate_id: str
    tests_passed: bool
    syntax_ok: bool
    score: float
    verified: bool
    critique: str = ''
    metadata: dict | None = None

class SyntheticDataLab:
    """Offline-first self-training lab. Generation is injected; verification is independent."""
    def __init__(self, timeout_s: float = 3.0, max_output: int = 12000):
        if timeout_s <= 0 or max_output <= 0:
            raise ValueError('limits must be positive')
        self.timeout_s = float(timeout_s)
        self.max_output = int(max_output)

    @staticmethod
    def fingerprint(text: str) -> str:
        return hashlib.sha256(text.encode('utf-8')).hexdigest()

    def syntax_check(self, code: str) -> tuple[bool, str]:
        try:
            ast.parse(code)
            return True, ''
        except SyntaxError as e:
            return False, f'{e.msg} at line {e.lineno}'

    def _sandbox_python(self, code: str, tests: str) -> tuple[bool, str]:
        # Best-effort subprocess isolation only. Production deployments should use a container/VM.
        payload = code.rstrip() + '\n\n' + tests.rstrip() + '\n'
        if len(payload) > self.max_output * 2:
            return False, 'payload_too_large'
        with tempfile.TemporaryDirectory(prefix='pfai-synth-') as td:
            p = Path(td) / 'candidate.py'
            p.write_text(payload, encoding='utf-8')
            try:
                r = subprocess.run([sys.executable, '-I', str(p)], cwd=td,
                    capture_output=True, text=True, timeout=self.timeout_s)
            except subprocess.TimeoutExpired:
                return False, 'timeout'
            out = ((r.stdout or '') + (r.stderr or ''))[:self.max_output]
            return r.returncode == 0, out

    def verify_python(self, code: str, tests: str) -> tuple[bool, str]:
        ok, reason = self.syntax_check(code)
        if not ok:
            return False, reason
        return self._sandbox_python(code, tests)

    def evaluate(self, task: SyntheticTask, response: str,
                 verifier: Optional[Callable[[str], tuple[bool, str]]] = None,
                 tests: str = '') -> Candidate:
        syntax_ok, syntax_reason = self.syntax_check(response)
        if not syntax_ok:
            score = 0.0
            passed = False
            critique = syntax_reason
        else:
            if verifier is None:
                passed, critique = self.verify_python(response, tests) if tests else (False, 'no_verifier')
            else:
                passed, critique = verifier(response)
            score = 1.0 if passed else 0.25
        cid = self.fingerprint(task.task_id + '\n' + response)
        return Candidate(task.task_id, response, cid, passed, syntax_ok, score,
                         verified=bool(syntax_ok and passed), critique=critique,
                         metadata={'track': task.track, 'difficulty': task.difficulty})

    def generate_and_verify(self, tasks: Iterable[SyntheticTask], generator: Callable[[SyntheticTask], str],
                            tests_by_task: Optional[dict[str, str]] = None) -> list[Candidate]:
        accepted=[]
        seen=set()
        tests_by_task = tests_by_task or {}
        for task in tasks:
            response = str(generator(task))
            c = self.evaluate(task, response, tests=tests_by_task.get(task.task_id, ''))
            if c.verified and c.candidate_id not in seen:
                accepted.append(c); seen.add(c.candidate_id)
        return accepted

    def export_training_jsonl(self, candidates: Iterable[Candidate], path: str | Path) -> dict:
        path=Path(path); path.parent.mkdir(parents=True, exist_ok=True)
        rows=[c for c in candidates if c.verified]
        with path.open('w', encoding='utf-8') as f:
            for c in rows:
                f.write(json.dumps({'instruction': c.task_id, 'response': c.response,
                                    'candidate_id': c.candidate_id, 'verified': True,
                                    'metadata': c.metadata}, ensure_ascii=False)+'\n')
        return {'path': str(path), 'total': len(rows),
                'fingerprint': self.fingerprint('\n'.join(c.candidate_id for c in rows))}
