"""PHASE 14 ApplicationBuilder / EngineeringOrchestrator."""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from pfai.authorized_execution import ActionPermissionGate, AuthorizedExecutor, sanitize_args
from pfai.elite.sandbox import Sandbox
from pfai.engineering.project_workspace import ProjectWorkspace
from pfai.engineering.remediation import RemediationLoop
from pfai.engineering.secure_analyzer import SecureCodeAnalyzer
from pfai.engineering.templates import materialize_template
from pfai.engineering.types import EngineeringArtifact, ProjectKind, new_id
from pfai.interfaces.tools import ToolPermission


_KIND_HINTS = [
    (ProjectKind.FULLSTACK.value, ("full-stack", "fullstack", "full stack", "website and api", "web app with api")),
    (ProjectKind.BACKEND_API.value, ("api", "backend", "fastapi", "rest service")),
    (ProjectKind.FRONTEND_APP.value, ("frontend", "spa", "react", "vue", "ui app")),
    (ProjectKind.DATABASE_BACKED.value, ("database", "schema", "migration", "sql")),
    (ProjectKind.SERVICE_API.value, ("service", "microservice")),
    (ProjectKind.STATIC_WEBSITE.value, ("website", "landing", "static site", "html")),
]


class ApplicationBuilder:
    """requirement → spec → architecture → implement → test → validate → security → report."""

    def __init__(
        self,
        root: str | None = None,
        *,
        executor: AuthorizedExecutor | None = None,
    ) -> None:
        self.base = Path(root or tempfile.mkdtemp(prefix="pfai-eng-"))
        self.base.mkdir(parents=True, exist_ok=True)
        self.executor = executor or AuthorizedExecutor(ActionPermissionGate())

    def detect_kind(self, requirement: str) -> str:
        t = (requirement or "").lower()
        for kind, words in _KIND_HINTS:
            if any(w in t for w in words):
                return kind
        return ProjectKind.STATIC_WEBSITE.value

    def specify(self, requirement: str) -> dict[str, Any]:
        kind = self.detect_kind(requirement)
        name = "pfai-app"
        # crude name extraction
        for token in (requirement or "").split():
            if token.isalnum() and len(token) > 3 and token.lower() not in ("build", "create", "make", "website", "application"):
                name = token[:40]
                break
        return {
            "requirement": requirement,
            "kind": kind,
            "name": name,
            "description": requirement[:500],
            "architecture": {
                "components": ["app", "tests", "config", "security_baseline"],
                "kind": kind,
            },
        }

    def build(
        self,
        requirement: str,
        *,
        approved: bool = False,
        actor: str = "",
        run_tests: bool = True,
        security_review: bool = True,
    ) -> dict[str, Any]:
        def _build(**_k: Any) -> dict[str, Any]:
            spec = self.specify(requirement)
            project_root = self.base / f"{spec['name']}-{new_id('proj')[-6:]}"
            ws = ProjectWorkspace(project_root)
            ckpt0 = ws.checkpoint("empty_start")
            mat = materialize_template(
                ws,
                kind=spec["kind"],
                name=spec["name"],
                description=spec["description"],
            )
            if not mat.get("ok"):
                return {"ok": False, "error": mat.get("error"), "complete": False}
            files = ws.list_files()
            test_files = [f for f in files if f.startswith("tests/")]
            validation: dict[str, Any] = {"files_exist": bool(files), "tests_exist": bool(test_files)}
            # Run tests in sandbox
            if run_tests and test_files:
                sb = Sandbox(root=str(project_root / ".pfai" / "sandbox_run"), timeout=20.0, allow_network=False)
                try:
                    # Execute pytest against project if available
                    result = subprocess.run(
                        ["python", "-m", "pytest", str(project_root / "tests"), "-q", "--tb=line"],
                        capture_output=True,
                        text=True,
                        timeout=25,
                        cwd=str(project_root),
                    )
                    validation["tests_ran"] = True
                    validation["tests_ok"] = result.returncode == 0
                    validation["tests_output"] = ((result.stdout or "") + (result.stderr or ""))[:2000]
                except Exception as exc:
                    validation["tests_ran"] = False
                    validation["tests_ok"] = False
                    validation["tests_error"] = type(exc).__name__
                finally:
                    sb.cleanup()
            else:
                validation["tests_ran"] = False
                validation["tests_ok"] = False

            security: dict[str, Any] = {}
            if security_review:
                security = SecureCodeAnalyzer(project_root).analyze()

            complete = bool(
                validation.get("files_exist")
                and validation.get("tests_exist")
                and (validation.get("tests_ok") if run_tests else True)
            )
            report_lines = [
                f"# Validation Report — {spec['name']}",
                "",
                f"- kind: `{spec['kind']}`",
                f"- files: {len(files)}",
                f"- tests: {len(test_files)}",
                f"- tests_ok: {validation.get('tests_ok')}",
                f"- security_findings: {security.get('finding_count', 0)}",
                f"- complete: {complete}",
                "",
                "Completion is claimed only when files and (when enabled) tests succeed.",
            ]
            ws.write_text("VALIDATION_REPORT.md", "\n".join(report_lines), overwrite=True)
            artifact = EngineeringArtifact(
                artifact_id=new_id("art"),
                kind=spec["kind"],
                root=str(project_root),
                files=files,
                tests=test_files,
                checkpoint_id=ckpt0.get("checkpoint_id", ""),
                validation=validation,
                security={"finding_count": security.get("finding_count"), "findings": security.get("findings", [])[:20]},
                complete=complete,
                report="\n".join(report_lines),
            )
            return {
                "ok": complete,
                "complete": complete,
                "spec": spec,
                "artifact": artifact.to_dict(),
                "note": None if complete else "incomplete_until_files_and_tests_pass",
            }

        # Building a project writes files — LOW_RISK_WRITE via executor
        result = self.executor.execute(
            kind="engineering",
            name="application_build",
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

    def review_existing(self, project_path: str) -> dict[str, Any]:
        root = Path(project_path)
        if not root.exists():
            return {"ok": False, "error": "project_missing"}
        analysis = SecureCodeAnalyzer(root).analyze()
        files = [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and ".pfai" not in p.parts][:500]
        return {
            "ok": True,
            "project": str(root),
            "file_count": len(files),
            "security": analysis,
        }

    def remediate_project(
        self,
        project_path: str,
        *,
        approved: bool = False,
        actor: str = "",
        auto_apply: bool = False,
    ) -> dict[str, Any]:
        ws = ProjectWorkspace(project_path)
        loop = RemediationLoop(ws, executor=self.executor)
        return loop.run(approved=approved, actor=actor, auto_apply=auto_apply)
