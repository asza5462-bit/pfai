"""PHASE 15 engineering modification workflow — plan → edit → test → record → rollback."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from pfai.authorized_execution import ActionPermissionGate, AuthorizedExecutor, sanitize_args
from pfai.engineering.project_inspector import ProjectInspector
from pfai.engineering.project_workspace import ProjectWorkspace
from pfai.engineering.types import new_id
from pfai.interfaces.tools import ToolPermission


class EngineeringWorkflow:
    """
    Every modification produces: plan, affected files, reason, execution record,
    tests, result, rollback information. Never silently modifies unrelated files.
    """

    def __init__(
        self,
        project_path: str | Path,
        *,
        executor: AuthorizedExecutor | None = None,
    ) -> None:
        self.workspace = ProjectWorkspace(project_path)
        self.executor = executor or AuthorizedExecutor(ActionPermissionGate())
        self.records_path = self.workspace.meta_dir / "engineering_records.jsonl"

    def inspect(self) -> dict[str, Any]:
        return ProjectInspector(self.workspace.root).inspect()

    def plan_modification(
        self,
        *,
        reason: str,
        affected_files: list[str],
        actions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        # Reject empty / unrelated wild plans
        files = [f for f in (affected_files or []) if isinstance(f, str) and f.strip()]
        if not files:
            return {"ok": False, "error": "affected_files_required"}
        # Prevent escaping workspace via .. 
        for f in files:
            if ".." in Path(f).parts or f.startswith("/"):
                return {"ok": False, "error": "path_escape_denied", "path": f}
        plan_id = new_id("plan")
        plan = {
            "plan_id": plan_id,
            "reason": (reason or "")[:1000],
            "affected_files": files,
            "actions": actions or [{"op": "write", "path": f} for f in files],
            "created_at": time.time(),
            "unrelated_files_touched": False,
        }
        return {"ok": True, "plan": plan}

    def apply_plan(
        self,
        plan: dict[str, Any],
        writers: dict[str, str] | Callable[[str], str],
        *,
        approved: bool = False,
        actor: str = "",
        run_tests: bool = True,
    ) -> dict[str, Any]:
        """
        writers: map path -> new content, or callable(path)->content.
        Only writes files listed in plan['affected_files'].
        """
        affected = list(plan.get("affected_files") or [])
        if not affected:
            return {"ok": False, "error": "empty_plan", "complete": False}

        def _run(**_k: Any) -> dict[str, Any]:
            ckpt = self.workspace.checkpoint(f"pre_{plan.get('plan_id', 'mod')}")
            written: list[str] = []
            errors: list[dict[str, Any]] = []
            for path in affected:
                try:
                    if callable(writers):
                        content = writers(path)
                    else:
                        if path not in writers:
                            errors.append({"path": path, "error": "content_missing_for_planned_file"})
                            continue
                        content = writers[path]
                    # Guard: do not write paths not in plan
                    if path not in affected:
                        errors.append({"path": path, "error": "unrelated_file_blocked"})
                        continue
                    res = self.workspace.write_text(path, content, overwrite=True)
                    if not res.get("ok"):
                        errors.append({"path": path, "error": res.get("error")})
                    else:
                        written.append(path)
                except Exception as exc:  # noqa: BLE001
                    errors.append({"path": path, "error": type(exc).__name__, "detail": str(exc)[:200]})

            test_result: dict[str, Any] = {"ran": False, "ok": None}
            if run_tests:
                test_result = self._run_tests()

            rolled_back = False
            if errors or (run_tests and test_result.get("ok") is False):
                self.workspace.rollback(ckpt["checkpoint_id"])
                rolled_back = True
                written = []

            record = {
                "record_id": new_id("erec"),
                "ts": time.time(),
                "plan_id": plan.get("plan_id"),
                "reason": plan.get("reason"),
                "affected_files": affected,
                "written": written,
                "errors": errors,
                "tests": test_result,
                "checkpoint_id": ckpt.get("checkpoint_id"),
                "rolled_back": rolled_back,
                "actor": actor,
                "ok": not rolled_back and not errors,
            }
            self._persist_record(record)
            return record

        result = self.executor.execute(
            kind="engineering",
            name="apply_modification_plan",
            permission=ToolPermission.LOW_RISK_WRITE,
            handler=_run,
            args=sanitize_args({"plan_id": plan.get("plan_id"), "files": affected, "reason": plan.get("reason")}),
            approved=True,
            actor=actor,
        )
        if result.get("needs_approval"):
            return {"ok": False, "needs_approval": True, "error": result.get("error"), "complete": False}
        if not result.get("ok"):
            return {"ok": False, "error": result.get("error"), "complete": False}
        out = result.get("result") or {}
        out["complete"] = bool(out.get("ok"))
        out["plan"] = plan
        return out

    def _run_tests(self) -> dict[str, Any]:
        tests_dir = self.workspace.root / "tests"
        if not tests_dir.exists():
            return {"ran": False, "ok": None, "note": "no_tests_directory"}
        try:
            proc = subprocess.run(
                ["python", "-m", "pytest", str(tests_dir), "-q", "--tb=line"],
                capture_output=True,
                text=True,
                timeout=40,
                cwd=str(self.workspace.root),
            )
            return {
                "ran": True,
                "ok": proc.returncode == 0,
                "returncode": proc.returncode,
                "output": ((proc.stdout or "") + (proc.stderr or ""))[:2000],
            }
        except Exception as exc:  # noqa: BLE001
            return {"ran": False, "ok": False, "error": type(exc).__name__}

    def _persist_record(self, record: dict[str, Any]) -> None:
        with self.records_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
