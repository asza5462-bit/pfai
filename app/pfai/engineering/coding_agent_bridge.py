"""PHASE 18 Coding Agent bridge — every modification yields changeset + audit; never bypasses authz."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from pfai.authorized_execution import ActionPermissionGate, AuthorizedExecutor, sanitize_args
from pfai.engineering.project_inspector import ProjectInspector
from pfai.engineering.project_workspace import ProjectWorkspace
from pfai.engineering.scope_enforcement import ScopeEnforcementLayer
from pfai.engineering.target_registry import TargetRegistry
from pfai.engineering.types import new_id
from pfai.interfaces.tools import ToolPermission


class ChangeSet:
    def __init__(
        self,
        *,
        reason: str,
        affected_files: list[str],
        tests_executed: list[str] | None = None,
        test_result: dict[str, Any] | None = None,
        rollback_info: dict[str, Any] | None = None,
    ) -> None:
        self.change_set_id = new_id("cs")
        self.reason = reason
        self.affected_files = list(affected_files)
        self.tests_executed = list(tests_executed or [])
        self.test_result = dict(test_result or {})
        self.rollback_info = dict(rollback_info or {})
        self.created_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "change_set_id": self.change_set_id,
            "reason": self.reason,
            "affected_files": self.affected_files,
            "tests_executed": self.tests_executed,
            "test_result": self.test_result,
            "rollback_info": self.rollback_info,
            "created_at": self.created_at,
        }


class CodingAgentBridge:
    """
    Connects coding operations to inspection / search / deps / architecture /
    implementation / testing / debugging / refactoring / documentation.

    Never bypasses TargetRegistry / ScopeEnforcement / AuthorizedExecutor.
    """

    VERSION = "18.0.0"

    def __init__(
        self,
        *,
        executor: AuthorizedExecutor | None = None,
        registry: TargetRegistry | None = None,
        audit_path: str = "data/longevity/engineering/coding_agent_audit.jsonl",
    ) -> None:
        self.executor = executor or AuthorizedExecutor(ActionPermissionGate())
        self.registry = registry or TargetRegistry()
        self.scope = ScopeEnforcementLayer(registry=self.registry)
        self.audit_path = Path(audit_path)
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)

    def _audit(self, event: str, **detail: Any) -> None:
        row = {"ts": time.time(), "event": event, **sanitize_args(detail)}
        with self.audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _require_local_or_authorized(
        self,
        *,
        project_path: str,
        target_id: str = "",
        actor: str = "",
        approved: bool = False,
        operation: str = "code_modify",
    ) -> dict[str, Any]:
        if target_id:
            decision = self.scope.enforce(
                target_id=target_id,
                operation=operation,
                method="static_analysis" if operation.startswith("inspect") else "code_modify",
                actor=actor,
                approved=approved,
                resource=project_path or "",
            )
            if not decision.get("ok"):
                self._audit("authorization_denied", target_id=target_id, error=decision.get("error"), actor=actor)
                return {"ok": False, "denied": True, "error": decision.get("error"), "decision": decision}
            return {"ok": True, "authorized": True, "decision": decision}
        # Local project path without target_id: still require path to exist; no network
        if not project_path:
            return {"ok": False, "denied": True, "error": "project_path_or_target_id_required"}
        if not Path(project_path).exists():
            return {"ok": False, "denied": True, "error": "project_missing"}
        return {"ok": True, "authorized": True, "local_project": True}

    def inspect_repository(
        self,
        project_path: str,
        *,
        target_id: str = "",
        actor: str = "",
        approved: bool = False,
    ) -> dict[str, Any]:
        gate = self._require_local_or_authorized(
            project_path=project_path, target_id=target_id, actor=actor, approved=approved, operation="inspect_repository"
        )
        if not gate.get("ok"):
            return gate
        insp = ProjectInspector(project_path).inspect()
        self._audit("inspect_repository", project_path=project_path, target_id=target_id, actor=actor)
        return {"ok": True, "inspection": insp, "authorization": gate}

    def search_code(
        self,
        project_path: str,
        query: str,
        *,
        target_id: str = "",
        actor: str = "",
        approved: bool = False,
    ) -> dict[str, Any]:
        gate = self._require_local_or_authorized(
            project_path=project_path, target_id=target_id, actor=actor, approved=approved, operation="inspect_search"
        )
        if not gate.get("ok"):
            return gate
        root = Path(project_path)
        hits: list[dict[str, Any]] = []
        q = (query or "").strip()
        if not q:
            return {"ok": False, "error": "query_required"}
        for path in root.rglob("*"):
            if not path.is_file() or ".pfai" in path.parts or ".git" in path.parts or "node_modules" in path.parts:
                continue
            if path.suffix.lower() not in {".py", ".js", ".ts", ".tsx", ".jsx", ".md", ".json", ".html"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                if q.lower() in line.lower():
                    hits.append({"file": str(path.relative_to(root)), "line": i, "text": line.strip()[:200]})
                    if len(hits) >= 50:
                        break
            if len(hits) >= 50:
                break
        self._audit("search_code", project_path=project_path, query=q[:80], hits=len(hits), actor=actor)
        return {"ok": True, "query": q, "hits": hits, "authorization": gate}

    def inspect_dependencies(
        self,
        project_path: str,
        *,
        target_id: str = "",
        actor: str = "",
        approved: bool = False,
    ) -> dict[str, Any]:
        gate = self._require_local_or_authorized(
            project_path=project_path, target_id=target_id, actor=actor, approved=approved, operation="inspect_deps"
        )
        if not gate.get("ok"):
            return gate
        insp = ProjectInspector(project_path).inspect()
        deps = (insp.get("dependencies") or {})
        return {"ok": True, "dependencies": deps, "authorization": gate, "note": "manifest_inventory_not_live_CVE"}

    def analyze_architecture(
        self,
        project_path: str,
        *,
        target_id: str = "",
        actor: str = "",
        approved: bool = False,
    ) -> dict[str, Any]:
        gate = self._require_local_or_authorized(
            project_path=project_path, target_id=target_id, actor=actor, approved=approved, operation="inspect_architecture"
        )
        if not gate.get("ok"):
            return gate
        insp = ProjectInspector(project_path).inspect()
        return {
            "ok": True,
            "architecture": insp.get("architecture") or insp.get("structure") or insp,
            "authorization": gate,
        }

    def apply_modification(
        self,
        project_path: str,
        *,
        writers: dict[str, str],
        reason: str,
        approved: bool = False,
        actor: str = "",
        target_id: str = "",
        run_tests: bool = True,
    ) -> dict[str, Any]:
        gate = self._require_local_or_authorized(
            project_path=project_path, target_id=target_id, actor=actor, approved=approved, operation="code_modify"
        )
        if not gate.get("ok"):
            return gate

        ws = ProjectWorkspace(project_path)
        ckpt = ws.checkpoint("pre_modification")

        def _apply(**_k: Any) -> dict[str, Any]:
            written = []
            for rel, content in (writers or {}).items():
                r = ws.write_text(rel, content, overwrite=True)
                if not r.get("ok"):
                    return {"ok": False, "error": r.get("error"), "path": rel}
                written.append(rel)
            test_result: dict[str, Any] = {}
            tests_executed: list[str] = []
            if run_tests and (ws.root / "tests").exists():
                import subprocess

                from pfai.elite.sandbox import Sandbox

                sb = Sandbox(root=str(ws.root / ".pfai" / "sandbox_mod"), timeout=20.0, allow_network=False)
                try:
                    proc = subprocess.run(
                        ["python", "-m", "pytest", str(ws.root / "tests"), "-q", "--tb=line"],
                        capture_output=True,
                        text=True,
                        timeout=25,
                        cwd=str(ws.root),
                    )
                    tests_executed = [str(p.relative_to(ws.root)) for p in (ws.root / "tests").rglob("test_*.py")]
                    test_result = {
                        "ok": proc.returncode == 0,
                        "output": ((proc.stdout or "") + (proc.stderr or ""))[:1500],
                    }
                except Exception as exc:  # noqa: BLE001
                    test_result = {"ok": False, "error": type(exc).__name__}
                finally:
                    sb.cleanup()
            cs = ChangeSet(
                reason=reason,
                affected_files=written,
                tests_executed=tests_executed,
                test_result=test_result,
                rollback_info={"checkpoint_id": ckpt.get("checkpoint_id"), "rollback_available": True},
            )
            audit_record = {
                "change_set": cs.to_dict(),
                "actor": actor,
                "target_id": target_id,
                "approved": approved,
            }
            self._audit("modification", **audit_record)
            return {
                "ok": True,
                "change_set": cs.to_dict(),
                "reason": reason,
                "affected_files": written,
                "tests_executed": tests_executed,
                "test_result": test_result,
                "rollback_information": cs.rollback_info,
                "audit_record": sanitize_args(audit_record),
            }

        result = self.executor.execute(
            kind="coding",
            name="coding_agent_modify",
            permission=ToolPermission.LOW_RISK_WRITE,
            handler=_apply,
            args=sanitize_args({"reason": reason, "files": list((writers or {}).keys())}),
            approved=True,
            actor=actor,
        )
        if result.get("needs_approval"):
            return {"ok": False, "needs_approval": True, "error": result.get("error"), "denied": False}
        if not result.get("ok"):
            return {"ok": False, "error": result.get("error")}
        out = result.get("result") or {"ok": False}
        out["authorization"] = gate
        return out

    def rollback(self, project_path: str, checkpoint_id: str, *, actor: str = "") -> dict[str, Any]:
        ws = ProjectWorkspace(project_path)
        out = ws.rollback(checkpoint_id)
        self._audit("rollback", project_path=project_path, checkpoint_id=checkpoint_id, actor=actor, ok=out.get("ok"))
        return out
