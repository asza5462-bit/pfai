from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Optional
import json, subprocess, sys, tempfile, time

from .code_evaluation import PythonCodeEvaluator
from .data_acquisition import DataAcquisitionEngine

@dataclass(frozen=True)
class CodeTask:
    task_id: str
    prompt: str
    tests: str
    language: str = 'python'
    track: str = 'software_engineering'

@dataclass(frozen=True)
class CodeAttempt:
    attempt: int
    passed_static: bool
    passed_runtime: bool
    score: float
    stdout: str
    stderr: str
    error: str = ''
    code: str = ''

class RestrictedPythonRunner:
    """Best-effort local runner. This is a containment aid, not a hardened OS sandbox."""
    def __init__(self, timeout_seconds: float = 3.0, max_output: int = 12000):
        self.timeout_seconds = float(timeout_seconds)
        self.max_output = int(max_output)

    def run(self, code: str, tests: str) -> dict:
        with tempfile.TemporaryDirectory(prefix='pfai-code-') as td:
            root = Path(td)
            program = root / 'solution.py'
            harness = root / 'test_runner.py'
            program.write_text(code, encoding='utf-8')
            harness.write_text(
                "exec(compile(open('solution.py', encoding='utf-8').read(), 'solution.py', 'exec'), globals())\n" + tests + "\n",
                encoding='utf-8')
            env = {'PYTHONPATH': ''}
            try:
                p = subprocess.run(
                    [sys.executable, '-I', '-S', str(harness)],
                    cwd=td, env=env, capture_output=True, text=True,
                    timeout=self.timeout_seconds, check=False)
                return {
                    'passed': p.returncode == 0,
                    'returncode': p.returncode,
                    'stdout': p.stdout[:self.max_output],
                    'stderr': p.stderr[:self.max_output],
                }
            except subprocess.TimeoutExpired as exc:
                return {'passed': False, 'returncode': None, 'stdout': (exc.stdout or '')[:self.max_output] if isinstance(exc.stdout, str) else '',
                        'stderr': 'timeout', 'error': 'timeout'}

class CodeResearchLoop:
    """Bounded generate -> static check -> execute tests -> learn loop for Python engineering tasks."""
    def __init__(self, root='data/code_research', evaluator=None, runner=None, acquisition=None):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.evaluator = evaluator or PythonCodeEvaluator()
        self.runner = runner or RestrictedPythonRunner()
        self.acquisition = acquisition or DataAcquisitionEngine(__import__('pfai.learning_curriculum', fromlist=['LearningCurriculum']).LearningCurriculum())

    def _save(self, task_id, payload):
        p = self.root / f'{task_id}.json'
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        return str(p)

    def solve(self, task: CodeTask, generator: Callable[[CodeTask, Optional[CodeAttempt]], str], max_attempts: int = 3) -> dict:
        if task.language.lower() != 'python':
            raise ValueError('v1.7 runtime supports Python tasks only')
        attempts = []
        feedback = None
        for n in range(1, max_attempts + 1):
            code = generator(task, feedback)
            static = self.evaluator.evaluate(code)
            if not static.passed:
                result = CodeAttempt(n, False, False, 0.0, '', '', 'static gate failed', code)
                attempts.append(asdict(result)); feedback = result
                continue
            runtime = self.runner.run(code, task.tests)
            score = 1.0 if runtime['passed'] else 0.5
            result = CodeAttempt(n, True, bool(runtime['passed']), score, runtime.get('stdout',''), runtime.get('stderr',''), runtime.get('error',''), code)
            attempts.append(asdict(result))
            feedback = result
            if result.passed_runtime:
                break
        best = max(attempts, key=lambda x: x['score'], default=None)
        accepted = bool(best and best['passed_static'] and best['passed_runtime'])
        learning = None
        if accepted:
            # Curate exactly the code string that was actually executed and
            # verified above -- never re-invoke the generator here. generator
            # is typically a call to a non-deterministic model, so calling it
            # again to "get the code back" (the previous behavior) could
            # silently curate a different, never-executed piece of code under
            # a 'runtime_verified: True' label. That defeats the entire point
            # of ground-truth verification.
            learning = self.acquisition.curate([{
                'instruction': task.prompt,
                'response': best['code'],
                'source': 'code_research_loop',
                'track': task.track,
                'metadata': {'task_id': task.task_id, 'attempts': len(attempts), 'runtime_verified': True}
            }])
        payload = {'task': asdict(task), 'attempts': attempts, 'accepted': accepted, 'best': best,
                   'learning_items': len(learning or []), 'created_at': time.time()}
        self._save(task.task_id, payload)
        return payload
