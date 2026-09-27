"""PHASE 12 sandboxed execution abstraction — no secrets, bounded FS/commands."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


FORBIDDEN_ENV_KEYS = (
    "PASSWORD",
    "PASSCODE",
    "OTP",
    "SECRET",
    "TOKEN",
    "API_KEY",
    "OPENAI",
    "ANTHROPIC",
    "OWNER",
    "CREDENTIAL",
    "PRIVATE_KEY",
)


class Sandbox:
    """Isolated workspace with command abstraction and secret isolation."""

    def __init__(
        self,
        root: str | None = None,
        *,
        timeout: float = 5.0,
        max_output_bytes: int = 64_000,
        allow_network: bool = False,
    ) -> None:
        self._owns = root is None
        self.root = Path(root or tempfile.mkdtemp(prefix="pfai-sandbox-"))
        self.root.mkdir(parents=True, exist_ok=True)
        self.timeout = float(timeout)
        self.max_output_bytes = int(max_output_bytes)
        self.allow_network = bool(allow_network)
        self._audit: list[dict[str, Any]] = []

    def path(self, rel: str = ".") -> Path:
        target = (self.root / rel).resolve()
        if self.root.resolve() not in target.parents and target != self.root.resolve():
            raise PermissionError("path_escapes_sandbox")
        return target

    def write_text(self, rel: str, content: str) -> dict[str, Any]:
        p = self.path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        self._audit.append({"event": "write_text", "path": rel, "bytes": len(content)})
        return {"ok": True, "path": str(p)}

    def read_text(self, rel: str) -> dict[str, Any]:
        p = self.path(rel)
        if not p.exists():
            return {"ok": False, "error": "missing"}
        data = p.read_text(encoding="utf-8")
        return {"ok": True, "content": data[: self.max_output_bytes]}

    def _sanitized_env(self) -> dict[str, str]:
        env = {}
        for k, v in os.environ.items():
            uk = k.upper()
            if any(bad in uk for bad in FORBIDDEN_ENV_KEYS):
                continue
            # Drop obvious secret values
            if isinstance(v, str) and any(x in v.lower() for x in ("begin private key", "sk-")):
                continue
            env[k] = v
        env["PFAI_SANDBOX"] = "1"
        env["PFAI_SANDBOX_ROOT"] = str(self.root)
        if not self.allow_network:
            env["PFAI_SANDBOX_NETWORK"] = "deny"
        return env

    def run(
        self,
        command: list[str],
        *,
        timeout: float | None = None,
        cwd: str | None = None,
    ) -> dict[str, Any]:
        if not command or not isinstance(command, list):
            return {"ok": False, "error": "command_must_be_list"}
        # Refuse obvious privilege / secret probes
        joined = " ".join(command).lower()
        if any(x in joined for x in ("passwd", "shadow", "/etc/owner", "id_rsa", "authorized_keys")):
            return {"ok": False, "error": "forbidden_path_or_secret_probe"}
        work = self.path(cwd or ".")
        started = time.time()
        try:
            proc = subprocess.run(
                command,
                cwd=str(work),
                capture_output=True,
                text=True,
                timeout=float(timeout or self.timeout),
                env=self._sanitized_env(),
                check=False,
            )
            stdout = (proc.stdout or "")[: self.max_output_bytes]
            stderr = (proc.stderr or "")[: self.max_output_bytes]
            out = {
                "ok": proc.returncode == 0,
                "exit_code": proc.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "latency_seconds": time.time() - started,
                "network_allowed": self.allow_network,
            }
        except subprocess.TimeoutExpired:
            out = {"ok": False, "error": "timeout", "latency_seconds": time.time() - started}
        except Exception as exc:
            out = {"ok": False, "error": type(exc).__name__, "latency_seconds": time.time() - started}
        self._audit.append({"event": "run", "command": command[:8], "ok": out.get("ok")})
        return out

    def run_python(self, code: str, *, timeout: float | None = None) -> dict[str, Any]:
        rel = "_sandbox_main.py"
        self.write_text(rel, code)
        return self.run(["python3", rel], timeout=timeout)

    def cleanup(self) -> dict[str, Any]:
        if self._owns and self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)
        return {"ok": True, "cleaned": self._owns, "audit_events": len(self._audit)}

    def audit(self) -> list[dict[str, Any]]:
        return list(self._audit)
