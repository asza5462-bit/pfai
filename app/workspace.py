"""Project workspace, files, diffs, and bounded command execution."""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.config import settings
from app.database import db

IGNORE_NAMES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".next",
    "dist",
    "build",
}
ALLOWED_COMMANDS = {
    "python",
    "python3",
    "pytest",
    "ruff",
    "mypy",
    "npm",
    "npx",
    "pnpm",
    "yarn",
    "node",
    "git",
    "go",
    "cargo",
}
BLOCKED_GIT = {"push", "remote", "credential", "config"}
PROJECT_NAME_RE = re.compile(r"^[\w\u0600-\u06FF ._-]{1,80}$")


def _project_row(project_id: str, user_id: int) -> dict:
    row = db.one("SELECT * FROM projects WHERE id=? AND user_id=?", (project_id, user_id))
    if not row:
        raise HTTPException(404, "المشروع غير موجود")
    return row


def project_root(project_id: str, user_id: int) -> Path:
    _project_row(project_id, user_id)
    root = (settings.workspace_root / project_id).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_path(root: Path, relative: str, *, must_exist: bool = False) -> Path:
    relative = str(relative or "").replace("\\", "/").lstrip("/")
    if not relative or relative == ".":
        target = root
    else:
        if "\x00" in relative or any(part in {"", ".", ".."} for part in relative.split("/")):
            raise HTTPException(400, "مسار غير صالح")
        target = (root / relative).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise HTTPException(400, "المسار خارج المشروع") from exc
    if must_exist and not target.exists():
        raise HTTPException(404, "الملف غير موجود")
    if target.exists() and target.is_symlink():
        raise HTTPException(400, "الروابط الرمزية غير مسموحة")
    return target


def list_projects(user_id: int) -> list[dict]:
    rows = db.all("SELECT * FROM projects WHERE user_id=? ORDER BY updated_at DESC", (user_id,))
    for row in rows:
        root = settings.workspace_root / row["id"]
        row["file_count"] = sum(1 for p in root.rglob("*") if p.is_file() and ".git" not in p.parts) if root.exists() else 0
    return rows


def create_project(user_id: int, name: str, description: str = "", template: str = "blank") -> dict:
    name = name.strip()
    if not PROJECT_NAME_RE.fullmatch(name):
        raise HTTPException(400, "اسم المشروع غير صالح")
    project_id = uuid.uuid4().hex
    now = time.time()
    db.execute(
        "INSERT INTO projects(id, user_id, name, description, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (project_id, user_id, name, description.strip()[:500], now, now),
    )
    root = settings.workspace_root / project_id
    root.mkdir(parents=True, exist_ok=True)
    _apply_template(root, name, template)
    _run(["git", "init", "-q"], root, timeout=10)
    _run(["git", "add", "."], root, timeout=10)
    _run(
        ["git", "-c", "user.name=NOVA", "-c", "user.email=nova@local", "commit", "-qm", "Initial project"],
        root,
        timeout=10,
    )
    db.audit(user_id, "project.create", {"project_id": project_id, "template": template})
    return _project_row(project_id, user_id)


def _apply_template(root: Path, name: str, template: str) -> None:
    readme = f"# {name}\n\nBuilt with NOVA Code.\n"
    files: dict[str, str] = {"README.md": readme, ".gitignore": ".env\n__pycache__/\nnode_modules/\n"}
    if template == "python":
        files.update(
            {
                "main.py": 'def main() -> None:\n    print("Hello from NOVA")\n\n\nif __name__ == "__main__":\n    main()\n',
                "pyproject.toml": '[project]\nname = "nova-project"\nversion = "0.1.0"\nrequires-python = ">=3.11"\n',
                "tests/test_main.py": "def test_smoke() -> None:\n    assert True\n",
            }
        )
    elif template == "web":
        files.update(
            {
                "index.html": '<!doctype html><html><head><meta charset="utf-8"><title>NOVA App</title><link rel="stylesheet" href="style.css"></head><body><main><h1>Hello</h1></main><script src="app.js"></script></body></html>\n',
                "style.css": "body { font-family: system-ui; margin: 0; padding: 3rem; background: #0b1020; color: white; }\n",
                "app.js": 'console.log("Built with NOVA");\n',
            }
        )
    for path, content in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def delete_project(project_id: str, user_id: int) -> None:
    root = project_root(project_id, user_id)
    with db.transaction() as conn:
        conn.execute("DELETE FROM projects WHERE id=? AND user_id=?", (project_id, user_id))
    shutil.rmtree(root, ignore_errors=True)
    db.audit(user_id, "project.delete", {"project_id": project_id})


def tree(project_id: str, user_id: int) -> list[dict[str, Any]]:
    root = project_root(project_id, user_id)
    output: list[dict[str, Any]] = []

    def walk(directory: Path, depth: int = 0) -> list[dict[str, Any]]:
        if depth > 12:
            return []
        nodes = []
        try:
            entries = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError:
            return []
        for entry in entries:
            if entry.name in IGNORE_NAMES or entry.is_symlink() or entry.name.startswith(".git"):
                continue
            rel = entry.relative_to(root).as_posix()
            if entry.is_dir():
                nodes.append({"name": entry.name, "path": rel, "type": "directory", "children": walk(entry, depth + 1)})
            elif entry.is_file():
                nodes.append({"name": entry.name, "path": rel, "type": "file", "size": entry.stat().st_size})
        return nodes

    output.extend(walk(root))
    return output


def read_file(project_id: str, user_id: int, path: str) -> dict:
    root = project_root(project_id, user_id)
    target = safe_path(root, path, must_exist=True)
    if not target.is_file():
        raise HTTPException(400, "المسار ليس ملفاً")
    size = target.stat().st_size
    if size > settings.max_file_bytes:
        raise HTTPException(413, "الملف أكبر من حد العرض")
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(415, "الملف ثنائي ولا يمكن تحريره") from exc
    return {"path": path, "content": content, "size": size, "language": language_for(path)}


def write_file(project_id: str, user_id: int, path: str, content: str) -> dict:
    encoded_size = len(content.encode())
    if encoded_size > settings.max_file_bytes:
        raise HTTPException(413, "محتوى الملف أكبر من الحد")
    root = project_root(project_id, user_id)
    target = safe_path(root, path)
    previous_size = target.stat().st_size if target.exists() and target.is_file() else 0
    project_size = sum(
        item.stat().st_size
        for item in root.rglob("*")
        if item.is_file() and ".git" not in item.parts and not item.is_symlink()
    )
    if project_size - previous_size + encoded_size > settings.max_project_bytes:
        raise HTTPException(413, "المشروع تجاوز حد التخزين")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    db.execute("UPDATE projects SET updated_at=? WHERE id=?", (time.time(), project_id))
    db.audit(user_id, "file.write", {"project_id": project_id, "path": path, "bytes": len(content.encode())})
    return {"ok": True, "path": path, "size": target.stat().st_size}


def delete_file(project_id: str, user_id: int, path: str) -> None:
    root = project_root(project_id, user_id)
    target = safe_path(root, path, must_exist=True)
    if target == root:
        raise HTTPException(400, "لا يمكن حذف جذر المشروع")
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    db.execute("UPDATE projects SET updated_at=? WHERE id=?", (time.time(), project_id))
    db.audit(user_id, "file.delete", {"project_id": project_id, "path": path})


def language_for(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".html": "html",
        ".css": "css",
        ".json": "json",
        ".md": "markdown",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".sh": "shell",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
    }.get(suffix, "plaintext")


def git_diff(project_id: str, user_id: int) -> str:
    root = project_root(project_id, user_id)
    result = _run(["git", "diff", "--no-ext-diff", "--", "."], root, timeout=15)
    untracked = _run(["git", "ls-files", "--others", "--exclude-standard"], root, timeout=10)
    text = result["stdout"]
    if untracked["stdout"].strip():
        text += "\nUntracked files:\n" + untracked["stdout"]
    return text[:200_000]


def git_checkpoint(project_id: str, user_id: int, message: str) -> dict:
    root = project_root(project_id, user_id)
    _run(["git", "add", "."], root, timeout=15)
    result = _run(
        ["git", "-c", "user.name=NOVA", "-c", "user.email=nova@local", "commit", "-m", message[:120]],
        root,
        timeout=20,
    )
    db.audit(user_id, "git.checkpoint", {"project_id": project_id, "message": message[:120]})
    return result


def run_command(project_id: str, user_id: int, command: str) -> dict:
    if not settings.allow_commands:
        raise HTTPException(403, "تشغيل الأوامر معطّل")
    root = project_root(project_id, user_id)
    try:
        args = shlex.split(command)
    except ValueError as exc:
        raise HTTPException(400, "صيغة الأمر غير صحيحة") from exc
    if not args or args[0] not in ALLOWED_COMMANDS:
        raise HTTPException(403, f"الأمر {args[0] if args else ''} غير مسموح")
    if args[0] == "git" and len(args) > 1 and args[1] in BLOCKED_GIT:
        raise HTTPException(403, "عملية Git هذه غير مسموحة من الطرفية")
    if any("\x00" in part or len(part) > 1000 for part in args):
        raise HTTPException(400, "وسيط أمر غير صالح")
    result = _run(args, root, timeout=settings.command_timeout)
    db.audit(user_id, "command.run", {"project_id": project_id, "command": command[:300], "code": result["exit_code"]})
    return result


def _run(args: list[str], cwd: Path, *, timeout: int) -> dict:
    env = {
        "PATH": os.getenv("PATH", ""),
        "HOME": str(cwd),
        "PYTHONPATH": str(cwd),
        "CI": "1",
        "NO_COLOR": "1",
    }
    started = time.monotonic()
    try:
        process = subprocess.run(
            args,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            check=False,
        )
        stdout = process.stdout[-100_000:]
        stderr = process.stderr[-100_000:]
        return {
            "ok": process.returncode == 0,
            "exit_code": process.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "duration_ms": round((time.monotonic() - started) * 1000),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "exit_code": 124,
            "stdout": (exc.stdout or "")[-100_000:] if isinstance(exc.stdout, str) else "",
            "stderr": "انتهت مهلة تنفيذ الأمر",
            "duration_ms": round((time.monotonic() - started) * 1000),
        }
    except OSError as exc:
        return {
            "ok": False,
            "exit_code": 127,
            "stdout": "",
            "stderr": f"تعذّر تشغيل الأمر: {exc}",
            "duration_ms": round((time.monotonic() - started) * 1000),
        }
