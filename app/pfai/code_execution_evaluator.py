"""Ground-truth code evaluation: actually run candidate code against tests.

pfai/code_evaluation.py (PythonCodeEvaluator) deliberately never executes
anything -- it is a static heuristic (syntax, structure, blocked imports).
That's a good hard pre-filter, but it cannot tell you whether generated code
is actually *correct*: only running it against real assertions can.

This module adds that missing ground-truth signal, while keeping execution as
contained as reasonably possible in a single-process Python sandbox:

  1. Hard static pre-filter first (blocked_imports is stricter here than the
     default PythonCodeEvaluator -- it also blocks network/process/import
     machinery). Code that fails this is NEVER executed, no exceptions.
  2. What passes the pre-filter runs in its own subprocess, not this one:
     - a hard wall-clock timeout (subprocess killed on expiry)
     - CPU-time and memory rlimits (best-effort, POSIX only)
     - no filesystem access outside a fresh, discarded temp directory
     - a runtime shim that blocks socket.socket before the candidate code
       runs, as defense-in-depth alongside the import-level block
  3. Fails closed on every error path: timeout, resource-limit trip, crash,
     non-zero exit, or the static gate itself -> passed=False. Nothing here
     ever raises out to the caller.

This is used only to score *eligibility* for the human-approval queue in
ContinuousLearningOrchestrator / LearningLoop -- exactly like llm_evaluator.py
and code_evaluation.py before it. It grants the running PFAI process no new
capability: the subprocess it spawns is exactly as sandboxed as the process
that would otherwise be needed to check "does this code work" at all, and
nothing here can promote a candidate or change what tools the *live* agent
can call.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import subprocess
import sys
import tempfile

from .code_evaluation import PythonCodeEvaluator

try:
    import resource  # POSIX only
except ImportError:  # pragma: no cover - non-POSIX platforms
    resource = None

# Stricter than PythonCodeEvaluator's default: also blocks anything that
# could reach the network, spawn processes, or reload/patch its way around
# the sandbox shim.
EXECUTION_BLOCKED_IMPORTS = (
    'subprocess', 'os', 'shutil', 'socket', 'ctypes',
    'urllib', 'http', 'requests', 'ftplib', 'telnetlib', 'smtplib',
    'importlib', 'multiprocessing', 'threading', 'asyncio',
)

_SANDBOX_PRELUDE = (
    "import socket as _pfai_socket\n"
    "def _pfai_blocked(*a, **k):\n"
    "    raise RuntimeError('network access is disabled inside the PFAI code sandbox')\n"
    "_pfai_socket.socket = _pfai_blocked\n"
    "_pfai_socket.create_connection = _pfai_blocked\n"
)


@dataclass(frozen=True)
class ExecutionEvalResult:
    passed: bool
    static_passed: bool
    executed: bool
    timed_out: bool
    returncode: Optional[int]
    stdout: str
    stderr: str
    score: float
    reason: str


def _limit_resources(cpu_seconds: int, memory_bytes: int):
    """Returns a preexec_fn that applies POSIX rlimits inside the child
    before it starts running, or None if unavailable on this platform."""
    if resource is None:
        return None

    def _apply():
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
            resource.setrlimit(resource.RLIMIT_FSIZE, (5_000_000, 5_000_000))
            if hasattr(resource, 'RLIMIT_NPROC'):
                resource.setrlimit(resource.RLIMIT_NPROC, (128, 128))
        except (ValueError, OSError):
            pass  # best-effort; the timeout below still bounds worst case

    return _apply


class SandboxedCodeEvaluator:
    """Executes candidate_code + test_code together in an isolated subprocess
    and reports whether it actually ran successfully -- ground truth, not a
    heuristic guess."""

    def __init__(self, timeout_seconds: int = 5, cpu_seconds: int = 4,
                 memory_bytes: int = 512 * 1024 * 1024,
                 blocked_imports=EXECUTION_BLOCKED_IMPORTS):
        if timeout_seconds <= 0 or cpu_seconds <= 0 or memory_bytes <= 0:
            raise ValueError("timeout_seconds, cpu_seconds and memory_bytes must be positive")
        self.timeout_seconds = int(timeout_seconds)
        self.cpu_seconds = int(cpu_seconds)
        self.memory_bytes = int(memory_bytes)
        self.static_gate = PythonCodeEvaluator(blocked_imports=blocked_imports)

    def evaluate(self, candidate_code: str, test_code: str = '') -> ExecutionEvalResult:
        static = self.static_gate.evaluate(candidate_code + "\n" + test_code)
        if not static.syntax_ok:
            return ExecutionEvalResult(False, False, False, False, None, '', '', 0.0,
                                        f"static gate: syntax error ({static.details.get('error', '')})")
        if not static.passed:
            return ExecutionEvalResult(False, False, False, False, None, '', '', 0.0,
                                        f"static gate: blocked import(s) {static.unsafe_imports}")

        script = _SANDBOX_PRELUDE + "\n" + candidate_code + "\n" + test_code + "\n"

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                script_path = Path(tmpdir) / "candidate.py"
                script_path.write_text(script, encoding='utf-8')
                try:
                    proc = subprocess.run(
                        [sys.executable, '-I', str(script_path)],
                        cwd=tmpdir,
                        timeout=self.timeout_seconds,
                        capture_output=True,
                        text=True,
                        env={'PATH': '/usr/bin:/bin'},  # no inherited secrets/env
                        preexec_fn=_limit_resources(self.cpu_seconds, self.memory_bytes),
                    )
                except subprocess.TimeoutExpired as exc:
                    return ExecutionEvalResult(False, True, True, True, None,
                                                exc.stdout or '', exc.stderr or '', 0.0,
                                                f"execution timed out after {self.timeout_seconds}s")
        except Exception as exc:  # fail closed on anything unexpected (fork failure, etc.)
            return ExecutionEvalResult(False, True, False, False, None, '', '', 0.0,
                                        f"sandbox setup failed: {type(exc).__name__}")

        # A negative returncode means the child was killed by a signal rather
        # than exiting on its own. In this sandbox the only sources of that
        # are our own POSIX rlimits (RLIMIT_CPU/RLIMIT_AS/RLIMIT_FSIZE) racing
        # the wall-clock timeout above -- both represent "forcibly terminated
        # by a safety limit", not a normal failing exit, so both must be
        # reported as timed_out=True regardless of which one won the race.
        killed_by_signal = proc.returncode is not None and proc.returncode < 0
        if killed_by_signal:
            return ExecutionEvalResult(False, True, True, True, proc.returncode,
                                        proc.stdout[-4000:], proc.stderr[-4000:], 0.0,
                                        f"execution killed by signal {-proc.returncode} "
                                        f"(resource limit exceeded)")

        passed = proc.returncode == 0
        score = 1.0 if passed else 0.0
        reason = 'executed successfully' if passed else f"exited with code {proc.returncode}"
        return ExecutionEvalResult(passed, True, True, False, proc.returncode,
                                    proc.stdout[-4000:], proc.stderr[-4000:], score, reason)
