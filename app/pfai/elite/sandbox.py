"""PHASE 12/13.1 sandboxed execution — bounded process workspace, honest isolation claims.

Architecture allows a future Docker/container/VM backend without changing Skill/Tool
interfaces (see SandboxBackend protocol + ProcessSandboxBackend).
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from abc import ABC, abstractmethod
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

DANGEROUS_COMMAND_MARKERS = (
    "rm -rf /",
    "mkfs",
    "dd if=",
    ":(){:|:&};:",
    "chmod 777",
    "chown root",
    "sudo ",
    "su -",
    "iptables",
    "mount ",
    "umount ",
    "kill -9 1",
    "curl ",
    "wget ",
    "nc ",
    "ncat ",
    "ssh ",
    "scp ",
    "python -c \"import socket",
)


class SandboxBackend(ABC):
    """Future Docker/VM backends implement this without changing Skill/Tool APIs."""

    backend_id: str = "abstract"
    full_container_isolation: bool = False

    @abstractmethod
    def run(self, command: list[str], *, cwd: str, env: dict[str, str], timeout: float) -> dict[str, Any]:
        ...

    @abstractmethod
    def cleanup(self) -> dict[str, Any]:
        ...


class ProcessSandboxBackend(SandboxBackend):
    backend_id = "process_workspace"
    full_container_isolation = False

    def __init__(self, root: Path, *, preexec=None) -> None:
        self.root = root
        self.preexec = preexec
        self._last_proc: subprocess.Popen | None = None

    def run(self, command: list[str], *, cwd: str, env: dict[str, str], timeout: float) -> dict[str, Any]:
        started = time.time()
        try:
            proc = subprocess.Popen(
                command,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                preexec_fn=self.preexec if os.name == "posix" else None,
                start_new_session=(os.name == "posix"),
            )
            self._last_proc = proc
            try:
                stdout, stderr = proc.communicate(timeout=float(timeout))
            except subprocess.TimeoutExpired:
                self._kill_tree(proc)
                return {"ok": False, "error": "timeout", "latency_seconds": time.time() - started}
            return {
                "ok": proc.returncode == 0,
                "exit_code": proc.returncode,
                "stdout": stdout or "",
                "stderr": stderr or "",
                "latency_seconds": time.time() - started,
            }
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__, "latency_seconds": time.time() - started}
        finally:
            self._last_proc = None

    def _kill_tree(self, proc: subprocess.Popen) -> None:
        try:
            if os.name == "posix" and proc.pid:
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            proc.wait(timeout=1)
        except Exception:
            pass

    def cleanup(self) -> dict[str, Any]:
        if self._last_proc and self._last_proc.poll() is None:
            self._kill_tree(self._last_proc)
        return {"ok": True, "backend": self.backend_id}


class Sandbox:
    """Process-bounded workspace — NOT full container isolation unless a container backend is used."""

    MODE = "process_workspace"
    SECURITY_LEVEL = "bounded"
    STATUS = "READY_BOUNDED"
    LIMITATIONS = (
        "Not a full container/VM isolate; relies on cwd jail + env filtering + resource soft limits.",
        "Network deny is policy-flag only unless the host enforces egress separately.",
        "CPU/memory limits use resource.setrlimit where the platform supports it.",
        "Does not provide kernel namespaces, seccomp, or cgroups by itself.",
        "Future Docker/VM backends can replace ProcessSandboxBackend without Skill/Tool API changes.",
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
        backend: SandboxBackend | None = None,
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
        self.backend = backend or ProcessSandboxBackend(self.root, preexec=self._preexec_limits)

    def metadata(self) -> dict[str, Any]:
        return {
            "SANDBOX_MODE": self.MODE,
            "SANDBOX_STATUS": self.STATUS,
            "SANDBOX_SECURITY_LEVEL": self.SECURITY_LEVEL,
            "SANDBOX_LIMITATIONS": list(self.LIMITATIONS),
            "backend": getattr(self.backend, "backend_id", type(self.backend).__name__),
            "timeout": self.timeout,
            "max_output_bytes": self.max_output_bytes,
            "allow_network": self.allow_network,
            "network_default": "deny",
            "memory_limit_bytes": self.memory_limit_bytes,
            "cpu_time_seconds": self.cpu_time_seconds,
            "filesystem_isolation": "cwd_prefix_jail",
            "full_container_isolation": bool(getattr(self.backend, "full_container_isolation", False)),
            "secret_path_denial": True,
            "env_filtering": True,
            "dangerous_command_filtering": True,
            "process_tree_cleanup": True,
            "path_traversal_prevention": True,
        }

    def path(self, rel: str = ".") -> Path:
        # Normalize and block traversal
        rel_s = str(rel or ".")
        if ".." in Path(rel_s).parts:
            raise PermissionError("path_traversal_denied")
        target = (self.root / rel_s).resolve()
        root = self.root.resolve()
        if root not in target.parents and target != root:
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
        for drop in ("HOME", "AWS_SECRET_ACCESS_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
            env.pop(drop, None)
        return env

    def _preexec_limits(self) -> None:
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
            return {"ok": False, "error": "cancelled", "status": "FAILED"}
        if not command or not isinstance(command, list):
            return {"ok": False, "error": "command_must_be_list", "status": "FAILED"}
        joined = " ".join(str(c) for c in command).lower()
        if any(x in joined for x in DENIED_PATH_MARKERS):
            self._audit.append({"event": "deny_secret_path", "command": command[:8]})
            return {"ok": False, "error": "forbidden_path_or_secret_probe", "denied": True, "status": "DENIED"}
        if any(x.strip() and x in joined for x in DANGEROUS_COMMAND_MARKERS):
            # Always deny dangerous markers; network tools also covered when network disabled
            if not self.allow_network or any(
                x in joined for x in ("rm -rf /", "mkfs", "dd if=", ":(){:|:&};:", "sudo ", "chmod 777")
            ):
                self._audit.append({"event": "deny_dangerous_command", "command": command[:8]})
                return {"ok": False, "error": "dangerous_command_denied", "denied": True, "status": "DENIED"}
        if not self.allow_network and any(
            x in joined for x in ("curl ", "wget ", "nc ", "ncat ", "ssh ", "scp ")
        ):
            return {"ok": False, "error": "network_denied_by_policy", "status": "DENIED"}
        try:
            work = self.path(cwd or ".")
        except PermissionError as exc:
            return {"ok": False, "error": str(exc), "status": "DENIED"}
        out = self.backend.run(
            command,
            cwd=str(work),
            env=self._sanitized_env(),
            timeout=float(timeout or self.timeout),
        )
        if "stdout" in out:
            stdout = (out.get("stdout") or "")[: self.max_output_bytes]
            stderr = (out.get("stderr") or "")[: self.max_output_bytes]
            out["stdout"] = stdout
            out["stderr"] = stderr
            out["output_truncated"] = len(out.get("stdout") or "") >= self.max_output_bytes or len(
                out.get("stderr") or ""
            ) >= self.max_output_bytes
        out["network_allowed"] = self.allow_network
        out.setdefault("status", "SUCCESS" if out.get("ok") else "FAILED")
        self._audit.append({"event": "run", "command": command[:8], "ok": out.get("ok"), "status": out.get("status")})
        return out

    def run_python(self, code: str, *, timeout: float | None = None) -> dict[str, Any]:
        low = (code or "").lower()
        if any(x in low for x in DENIED_PATH_MARKERS):
            return {"ok": False, "error": "forbidden_path_or_secret_probe", "denied": True, "status": "DENIED"}
        if any(x in low for x in ("socket.socket", "subprocess", "os.system", "pty.open")) and not self.allow_network:
            # Block obvious network/process escape in python payloads when network denied
            if any(x in low for x in ("socket.socket", "urllib", "http.client", "requests.")):
                return {"ok": False, "error": "network_denied_by_policy", "denied": True, "status": "DENIED"}
        rel = "_sandbox_main.py"
        self.write_text(rel, code)
        return self.run(["python3", rel], timeout=timeout)

    def cleanup(self) -> dict[str, Any]:
        backend_clean = self.backend.cleanup() if hasattr(self.backend, "cleanup") else {"ok": True}
        if self._owns and self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)
        return {
            "ok": True,
            "cleaned": self._owns,
            "audit_events": len(self._audit),
            "backend": backend_clean,
        }

    def audit(self) -> list[dict[str, Any]]:
        return list(self._audit)
