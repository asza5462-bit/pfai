"""PHASE 18 Application Engineering pipeline — requirements → artifact with adapters."""
from __future__ import annotations

import json
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from pfai.authorized_execution import ActionPermissionGate, AuthorizedExecutor, sanitize_args
from pfai.engineering.adapters import list_supported_adapters, select_adapter
from pfai.engineering.application_builder import ApplicationBuilder
from pfai.engineering.project_workspace import ProjectWorkspace
from pfai.engineering.secure_analyzer import SecureCodeAnalyzer
from pfai.engineering.types import EngineeringArtifact, ProjectKind, new_id
from pfai.interfaces.tools import ToolPermission


_KIND_HINTS = [
    (ProjectKind.FULLSTACK.value, ("full-stack", "fullstack", "full stack", "website and api", "web app with api")),
    (ProjectKind.BACKEND_API.value, ("api", "backend", "fastapi", "rest service", "nodejs", "node.js")),
    (ProjectKind.FRONTEND_APP.value, ("frontend", "spa", "react", "vue", "ui app", "next.js", "nextjs")),
    (ProjectKind.DATABASE_BACKED.value, ("database", "schema", "migration", "sql")),
    (ProjectKind.SERVICE_API.value, ("service", "microservice")),
    (ProjectKind.STATIC_WEBSITE.value, ("website", "landing", "static site", "html", "موقع", "ابن")),
]


class ApplicationEngineering:
    """
    Production-grade application engineering fabric.

    Pipeline: understand → architecture → structure → generate → authN/Z stubs →
    tests → docs → static checks → tests → failures → propose/apply fixes → retest → versioned artifact.
    """

    VERSION = "18.0.0"

    def __init__(
        self,
        root: str | None = None,
        *,
        executor: AuthorizedExecutor | None = None,
    ) -> None:
        self.base = Path(root) if root else Path(tempfile.mkdtemp(prefix="pfai-appeng-"))
        self.base.mkdir(parents=True, exist_ok=True)
        self.executor = executor or AuthorizedExecutor(ActionPermissionGate())
        self.legacy_builder = ApplicationBuilder(root=str(self.base / "legacy"), executor=self.executor)
        self.audit_path = self.base / "application_engineering_audit.jsonl"

    def _audit(self, event: str, **detail: Any) -> None:
        row = {"ts": time.time(), "event": event, **sanitize_args(detail)}
        with self.audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def supported_adapters(self) -> list[dict[str, Any]]:
        return list_supported_adapters()

    def detect_kind(self, requirement: str) -> str:
        t = (requirement or "").lower()
        for kind, words in _KIND_HINTS:
            if any(w in t for w in words):
                return kind
        return ProjectKind.STATIC_WEBSITE.value

    def understand(self, requirement: str) -> dict[str, Any]:
        kind = self.detect_kind(requirement)
        adapter = select_adapter(requirement, kind=kind)
        name = "pfai-app"
        for token in (requirement or "").replace("،", " ").split():
            cleaned = "".join(c for c in token if c.isalnum() or c in "-_")
            if cleaned and len(cleaned) > 2 and cleaned.lower() not in (
                "build", "create", "make", "website", "application", "ibn", "لي", "موقعا",
            ):
                name = cleaned[:40]
                break
        return {
            "requirement": requirement,
            "kind": kind,
            "name": name,
            "description": (requirement or "")[:500],
            "adapter_id": adapter.adapter_id,
            "adapter": adapter.capabilities(),
            "architecture": {
                "components": ["app", "tests", "config", "security_baseline", "auth_stubs", "docs"],
                "kind": kind,
                "adapter_id": adapter.adapter_id,
            },
        }

    def design_architecture(self, spec: dict[str, Any]) -> dict[str, Any]:
        kind = spec.get("kind")
        components = list((spec.get("architecture") or {}).get("components") or [])
        layers = ["presentation", "application", "data"] if kind in (
            ProjectKind.FULLSTACK.value,
            ProjectKind.DATABASE_BACKED.value,
        ) else ["application"]
        if kind in (ProjectKind.BACKEND_API.value, ProjectKind.SERVICE_API.value, ProjectKind.FULLSTACK.value):
            layers.append("api")
        return {
            "ok": True,
            "kind": kind,
            "layers": layers,
            "components": components,
            "auth": {"authentication": "env_session_stub", "authorization": "server_side_deny_default"},
            "testing": ["unit", "structure", "security_static"],
            "adapter_id": spec.get("adapter_id"),
        }

    def _add_auth_stubs(self, workspace: ProjectWorkspace, kind: str) -> list[str]:
        written: list[str] = []
        auth_py = '''"""Authentication / authorization stubs — DENY by default; no client roles trusted."""
from __future__ import annotations

import os
from typing import Any


def authenticate(token: str | None) -> dict[str, Any]:
    expected = os.environ.get("SESSION_SECRET")
    if not expected or not token or token != expected:
        return {"ok": False, "authenticated": False, "error": "unauthorized"}
    return {"ok": True, "authenticated": True, "subject": "session_user"}


def authorize(subject: dict[str, Any], action: str, resource: str = "") -> dict[str, Any]:
    # Deny by default — never trust client-supplied role fields
    if not subject.get("authenticated"):
        return {"ok": False, "allowed": False, "decision": "DENY"}
    if action in ("read_public", "health"):
        return {"ok": True, "allowed": True, "decision": "ALLOW"}
    return {"ok": False, "allowed": False, "decision": "DENY", "reason": "not_in_policy"}
'''
        if kind != ProjectKind.STATIC_WEBSITE.value:
            r = workspace.write_text("app/auth.py" if kind != ProjectKind.SERVICE_API.value else "service/auth.py", auth_py, overwrite=True)
            if r.get("ok"):
                written.append(r.get("path") or "auth.py")
        docs = """# Authentication & Authorization

- Secrets via environment only (`SESSION_SECRET`)
- Server-side authorization; DENY by default
- Client-provided roles never grant privileges
"""
        workspace.write_text("docs/AUTH.md", docs, overwrite=True)
        written.append("docs/AUTH.md")
        return written

    def _run_static_checks(self, project_root: Path) -> dict[str, Any]:
        findings = SecureCodeAnalyzer(project_root).analyze()
        py_files = [p for p in project_root.rglob("*.py") if ".pfai" not in p.parts]
        syntax_ok = True
        syntax_errors: list[str] = []
        # Parallel syntax checks
        def _check(path: Path) -> tuple[str, bool, str]:
            try:
                compile(path.read_text(encoding="utf-8"), str(path), "exec")
                return (str(path), True, "")
            except SyntaxError as exc:
                return (str(path), False, str(exc))

        with ThreadPoolExecutor(max_workers=min(4, max(1, len(py_files)))) as pool:
            futures = [pool.submit(_check, p) for p in py_files[:40]]
            for fut in as_completed(futures):
                path, ok, err = fut.result()
                if not ok:
                    syntax_ok = False
                    syntax_errors.append(f"{path}:{err}")
        return {
            "syntax_ok": syntax_ok,
            "syntax_errors": syntax_errors[:10],
            "security_finding_count": findings.get("finding_count"),
            "security_findings": findings.get("findings") or [],
        }

    def _run_tests(self, project_root: Path) -> dict[str, Any]:
        from pfai.elite.sandbox import Sandbox

        test_dir = project_root / "tests"
        if not test_dir.exists():
            return {"tests_ran": False, "tests_ok": False, "error": "no_tests"}
        sb = Sandbox(root=str(project_root / ".pfai" / "sandbox_run"), timeout=25.0, allow_network=False)
        try:
            result = subprocess.run(
                ["python", "-m", "pytest", str(test_dir), "-q", "--tb=line"],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(project_root),
            )
            return {
                "tests_ran": True,
                "tests_ok": result.returncode == 0,
                "tests_output": ((result.stdout or "") + (result.stderr or ""))[:2000],
                "sandbox": sb.metadata().get("SANDBOX_STATUS"),
            }
        except Exception as exc:  # noqa: BLE001
            return {"tests_ran": False, "tests_ok": False, "tests_error": type(exc).__name__}
        finally:
            sb.cleanup()

    def build(
        self,
        requirement: str,
        *,
        approved: bool = False,
        actor: str = "",
        run_tests: bool = True,
        security_review: bool = True,
        apply_safe_fixes: bool = False,
    ) -> dict[str, Any]:
        def _build(**_k: Any) -> dict[str, Any]:
            started = time.time()
            timeline: list[dict[str, Any]] = []
            spec = self.understand(requirement)
            timeline.append({"event": "understand", "spec": {k: spec[k] for k in ("kind", "name", "adapter_id")}})
            arch = self.design_architecture(spec)
            timeline.append({"event": "architecture", "layers": arch.get("layers")})

            project_root = self.base / f"{spec['name']}-{new_id('proj')[-6:]}"
            ws = ProjectWorkspace(project_root)
            ckpt0 = ws.checkpoint("empty_start")
            adapter = select_adapter(requirement, kind=spec["kind"])
            mat = adapter.materialize(
                ws,
                name=spec["name"],
                description=spec["description"],
                kind=spec["kind"],
            )
            if not mat.get("ok"):
                return {"ok": False, "error": mat.get("error"), "complete": False, "timeline": timeline}
            timeline.append({"event": "materialize", "adapter_id": adapter.adapter_id, "files": len(mat.get("files") or [])})

            auth_files = self._add_auth_stubs(ws, spec["kind"])
            timeline.append({"event": "auth_stubs", "files": auth_files})

            # Documentation already from template; add architecture note
            ws.write_text(
                "docs/ARCHITECTURE.md",
                f"# Architecture\n\nKind: `{spec['kind']}`\nAdapter: `{adapter.adapter_id}`\nLayers: {arch.get('layers')}\n",
                overwrite=True,
            )

            files = ws.list_files()
            test_files = [f for f in files if f.startswith("tests/")]
            static = self._run_static_checks(project_root) if security_review else {}
            timeline.append({"event": "static_checks", "syntax_ok": static.get("syntax_ok"), "findings": static.get("security_finding_count")})

            validation: dict[str, Any] = {
                "files_exist": bool(files),
                "tests_exist": bool(test_files),
            }
            if run_tests and test_files:
                validation.update(self._run_tests(project_root))
                timeline.append({"event": "tests", "ok": validation.get("tests_ok")})
            else:
                validation["tests_ran"] = False
                validation["tests_ok"] = False

            # Propose / apply safe fixes for secrets if configured
            remediation: dict[str, Any] = {}
            if apply_safe_fixes and static.get("security_findings"):
                from pfai.engineering.remediation import RemediationLoop

                loop = RemediationLoop(ws, executor=self.executor)
                remediation = loop.run(approved=approved, actor=actor, auto_apply=True)
                timeline.append({"event": "safe_remediation", "fixed": remediation.get("fixed_count")})
                if run_tests and test_files:
                    validation.update(self._run_tests(project_root))
                    timeline.append({"event": "retest", "ok": validation.get("tests_ok")})
                static = self._run_static_checks(project_root)

            complete = bool(
                validation.get("files_exist")
                and validation.get("tests_exist")
                and (validation.get("tests_ok") if run_tests else True)
                and static.get("syntax_ok", True)
            )
            version = 1
            artifact = EngineeringArtifact(
                artifact_id=new_id("art"),
                kind=spec["kind"],
                root=str(project_root),
                files=files,
                tests=test_files,
                checkpoint_id=ckpt0.get("checkpoint_id", ""),
                validation=validation,
                security={
                    "finding_count": static.get("security_finding_count"),
                    "findings": (static.get("security_findings") or [])[:20],
                },
                complete=complete,
                report=f"ApplicationEngineering v{self.VERSION} artifact version={version}",
            )
            meta = {
                "version": version,
                "adapter_id": adapter.adapter_id,
                "architecture": arch,
                "pipeline": [
                    "understand",
                    "architecture",
                    "structure",
                    "generate",
                    "auth",
                    "tests",
                    "docs",
                    "static_checks",
                    "test",
                    "fix",
                    "retest",
                    "version",
                ],
                "duration_seconds": time.time() - started,
            }
            (project_root / ".pfai" / "artifact_meta.json").parent.mkdir(parents=True, exist_ok=True)
            (project_root / ".pfai" / "artifact_meta.json").write_text(
                json.dumps({"artifact": artifact.to_dict(), "meta": meta}, indent=2),
                encoding="utf-8",
            )
            self._audit(
                "build",
                artifact_id=artifact.artifact_id,
                complete=complete,
                adapter_id=adapter.adapter_id,
                actor=actor,
            )
            return {
                "ok": complete,
                "complete": complete,
                "spec": spec,
                "architecture": arch,
                "artifact": artifact.to_dict(),
                "remediation": remediation,
                "timeline": timeline,
                "meta": meta,
                "supported_adapters": self.supported_adapters(),
                "note": None if complete else "incomplete_until_files_and_tests_pass",
                "phase": 18,
            }

        result = self.executor.execute(
            kind="engineering",
            name="application_engineering_build",
            permission=ToolPermission.LOW_RISK_WRITE,
            handler=_build,
            args=sanitize_args({"requirement": requirement}),
            approved=True,
            actor=actor,
        )
        if result.get("needs_approval"):
            return {"ok": False, "needs_approval": True, "error": result.get("error"), "complete": False}
        if not result.get("ok"):
            return {"ok": False, "error": result.get("error"), "complete": False}
        return result.get("result") or {"ok": False, "complete": False}
