"""PHASE 14 project workspace — checkpoints before mutation; never silent overwrite."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from pfai.engineering.types import new_id


class ProjectWorkspace:
    """Isolated project root with version checkpoints before modifications."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.meta_dir = self.root / ".pfai"
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoints_dir = self.meta_dir / "checkpoints"
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)
        self.audit_path = self.meta_dir / "workspace_audit.jsonl"

    def _audit(self, event: str, **detail: Any) -> None:
        row = {"ts": time.time(), "event": event, **detail}
        with self.audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def rel(self, path: str | Path) -> Path:
        p = (self.root / path).resolve()
        if self.root not in p.parents and p != self.root:
            raise PermissionError("path_escapes_project_workspace")
        return p

    def write_text(self, rel: str, content: str, *, overwrite: bool = False) -> dict[str, Any]:
        target = self.rel(rel)
        if target.exists() and not overwrite:
            return {"ok": False, "error": "file_exists_use_checkpoint_and_overwrite", "path": rel}
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self._audit("write_text", path=rel, bytes=len(content), overwrite=overwrite)
        return {"ok": True, "path": rel}

    def read_text(self, rel: str) -> dict[str, Any]:
        target = self.rel(rel)
        if not target.exists():
            return {"ok": False, "error": "missing"}
        return {"ok": True, "content": target.read_text(encoding="utf-8")}

    def list_files(self, pattern: str = "**/*") -> list[str]:
        out = []
        for p in self.root.glob(pattern):
            if p.is_file() and ".pfai" not in p.parts:
                out.append(str(p.relative_to(self.root)))
        return sorted(out)

    def checkpoint(self, label: str = "pre_modify") -> dict[str, Any]:
        cid = new_id("ckpt")
        dest = self.checkpoints_dir / cid
        dest.mkdir(parents=True, exist_ok=True)
        # Copy project files excluding .pfai/checkpoints nesting explosion
        for p in self.root.rglob("*"):
            if not p.is_file():
                continue
            if ".pfai" in p.parts and "checkpoints" in p.parts:
                continue
            rel = p.relative_to(self.root)
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)
        meta = {"checkpoint_id": cid, "label": label, "ts": time.time()}
        (dest / "_checkpoint.json").write_text(json.dumps(meta), encoding="utf-8")
        self._audit("checkpoint", **meta)
        return {"ok": True, **meta}

    def rollback(self, checkpoint_id: str) -> dict[str, Any]:
        src = self.checkpoints_dir / checkpoint_id
        if not src.exists():
            return {"ok": False, "error": "checkpoint_missing"}
        # Remove current files (except .pfai/checkpoints)
        for p in list(self.root.rglob("*")):
            if not p.is_file():
                continue
            if ".pfai" in p.parts and "checkpoints" in p.parts:
                continue
            if p.name == "workspace_audit.jsonl" and p.parent == self.meta_dir:
                continue
            try:
                p.unlink()
            except Exception:
                pass
        for p in src.rglob("*"):
            if not p.is_file() or p.name == "_checkpoint.json":
                continue
            rel = p.relative_to(src)
            target = self.root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)
        self._audit("rollback", checkpoint_id=checkpoint_id)
        return {"ok": True, "checkpoint_id": checkpoint_id}
