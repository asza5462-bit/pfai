"""PHASE 12/13 sandboxed execution — bounded, secrets denied, honest isolation claims."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

try:
    import resource
except ImportError:  # pragma: no cover
    resource = None  # type: ignore


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
    "SIGNING",
    "SESSION",
    "PFAI_SMTP",
    "PFAI_EMAIL_API",
)

# Paths / substrings sandbox commands must never touch
DENIED_PATH_MARKERS = (
    "passwd",
    "shadow",
    "/etc/owner",
    "id_rsa",
    "authorized_keys",
    "owner_credentials",
    "owner_otp",
    "owner_sessions",
    "owner_auth",
    ".ssh",
    "private_key",
    "signing_key",
    "api_keys",
    "secret_store",
    "credentials.json",
    "pfai_owner",
)


class Sandbox:
    """Process-bounded workspace — NOT full container isolation unless the OS provides it."""

    MODE = "process_workspace"
    SECURITY_LEVEL = "bounded"
    LIMITATIONS = (
        "Not a full container/VM isolate; relies on cwd jail + env filtering + resource soft limits.",
        "Network deny is policy-flag only unless the host enforces egress separately.",
        "CPU/memory limits use resource.setrlimit where the platform supports it.",
        "Does not provide kernel namespaces, seccomp, or cgroups by itself.",
    )

    def __init__(
        self,
        root: str | None = None,
        *,
        timeout: float = 5.0,
        max_output_bytes: int = 64_000,
        allow_network: bool = False,
        memory_limit_bytes: int | None = 256 * 1024 * 1024,
        cpu_time_seconds: int | None = 5,
    ) -> None:
        self._owns = root is None
        self.root = Path(root or tempfile.mkdtemp(prefix="pfai-sandbox-"))
        self.root.mkdir(parents=True, exist_ok=True)
        self.timeout = float(timeout)
        self.max_output_bytes = int(max_output_bytes)
        self.allow_network = bool(allow_network)
        self.memory_limit_bytes = memory_limit_bytes
        self.cpu_time_seconds = cpu_time_seconds
        self._audit: list[dict[str, Any]] = []
        self._cancelled = False
        self._lock = threading.RLock()

    def metadata(self) -> dict[str, Any]:
        return {
            "SANDBOX_MODE": self.MODE,
            "SANDBOX_SECURITY_LEVEL": self.SECURITY_LEVEL,
            "SANDBOX_LIMITATIONS": list(self.LIMITATIONS),
            "timeout": self.timeout,
            "max_output_bytes": self.max_output_bytes,
            "allow_network": self.allow_network,
            "memory_limit_bytes": self.memory_limit_bytes,
            "cpu_time_seconds": self.cpu_time_seconds,
            "filesystem_isolation": "cwd_prefix_jail",
            "full_container_isolation": False,
            "secret_path_denial": True,
            "env_filtering": True,
        }

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
            if isinstance(v, str) and any(x in v.lower() for x in ("begin private key", "sk-", "otp=")):
                continue
            env[k] = v
        env["PFAI_SANDBOX"] = "1"
        env["PFAI_SANDBOX_ROOT"] = str(self.root)
        if not self.allow_network:
            env["PFAI_SANDBOX_NETWORK"] = "deny"
        # Explicitly strip known secret paths from env copies
        for drop in ("HOME", "AWS_SECRET_ACCESS_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
            env.pop(drop, None)
        return env

    def _preexec_limits(self) -> None:
        """Best-effort rlimits — platforms without support are skipped."""
        if resource is None:
            return
        try:
            if self.cpu_time_seconds:
                resource.setrlimit(resource.RLIMIT_CPU, (int(self.cpu_time_seconds), int(self.cpu_time_seconds)))
        except Exception:
            pass
        try:
            if self.memory_limit_bytes:
                lim = int(self.memory_limit_bytes)
                resource.setrlimit(resource.RLIMIT_AS, (lim, lim))
        except Exception:
            pass
        try:
            if hasattr(os, "setpgrp"):
                os.setpgrp()
        except Exception:
            pass

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True

    def run(
        self,
        command: list[str],
        *,
        timeout: float | None = None,
        cwd: str | None = None,
    ) -> dict[str, Any]:
        if self._cancelled:
            return {"ok": False, "error": "cancelled"}
        if not command or not isinstance(command, list):
            return {"ok": False, "error": "command_must_be_list"}
        joined = " ".join(command).lower()
        if any(x in joined for x in DENIED_PATH_MARKERS):
            self._audit.append({"event": "deny_secret_path", "command": command[:8]})
            return {"ok": False, "error": "forbidden_path_or_secret_probe", "denied": True}
        if not self.allow_network and any(
            x in joined for x in ("curl ", "wget ", "nc ", "ncat ", "ssh ", "scp ")
        ):
            return {"ok": False, "error": "network_denied_by_policy"}
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
                preexec_fn=self._preexec_limits if os.name == "posix" else None,
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
                "output_truncated": len(proc.stdout or "") > self.max_output_bytes
                or len(proc.stderr or "") > self.max_output_bytes,
            }
        except subprocess.TimeoutExpired:
            out = {"ok": False, "error": "timeout", "latency_seconds": time.time() - started}
        except Exception as exc:
            out = {"ok": False, "error": type(exc).__name__, "latency_seconds": time.time() - started}
        self._audit.append({"event": "run", "command": command[:8], "ok": out.get("ok")})
        return out

    def run_python(self, code: str, *, timeout: float | None = None) -> dict[str, Any]:
        # Block obvious secret exfiltration in submitted code
        low = (code or "").lower()
        if any(x in low for x in DENIED_PATH_MARKERS):
            return {"ok": False, "error": "forbidden_path_or_secret_probe", "denied": True}
        rel = "_sandbox_main.py"
        self.write_text(rel, code)
        return self.run(["python3", rel], timeout=timeout)

    def cleanup(self) -> dict[str, Any]:
        if self._owns and self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)
        return {"ok": True, "cleaned": self._owns, "audit_events": len(self._audit)}

    def audit(self) -> list[dict[str, Any]]:
        return list(self._audit)
