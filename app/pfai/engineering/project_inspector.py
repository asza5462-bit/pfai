"""PHASE 15 — project / repository inspection (architecture, deps, structure)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


_DEP_FILES = (
    "requirements.txt",
    "pyproject.toml",
    "package.json",
    "Pipfile",
    "Cargo.toml",
    "go.mod",
    "Gemfile",
    "composer.json",
)


class ProjectInspector:
    """Inspect an existing project without modifying it."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def inspect(self) -> dict[str, Any]:
        if not self.root.exists() or not self.root.is_dir():
            return {"ok": False, "error": "project_missing", "root": str(self.root)}

        files: list[str] = []
        for p in self.root.rglob("*"):
            if not p.is_file():
                continue
            if any(part.startswith(".") and part not in (".env.example",) for part in p.parts):
                # skip hidden dirs like .git / .pfai / .venv except tracked config examples
                if ".git" in p.parts or ".venv" in p.parts or "__pycache__" in p.parts:
                    continue
                if ".pfai" in p.parts:
                    continue
            try:
                rel = str(p.relative_to(self.root))
            except ValueError:
                continue
            files.append(rel)
            if len(files) >= 800:
                break
        files = sorted(files)

        deps = self._dependencies(files)
        architecture = self._architecture_hints(files)
        tests = [f for f in files if f.startswith("tests/") or "/test_" in f or f.startswith("test_")]
        configs = [
            f
            for f in files
            if f.endswith((".env.example", ".toml", ".yaml", ".yml", ".ini", ".cfg", "Dockerfile"))
            or f in ("pyproject.toml", "package.json", "Makefile")
        ]
        return {
            "ok": True,
            "root": str(self.root),
            "file_count": len(files),
            "files": files[:200],
            "tests": tests[:100],
            "configs": configs[:50],
            "dependencies": deps,
            "architecture": architecture,
            "has_readme": any(f.lower().startswith("readme") for f in files),
            "has_tests": bool(tests),
            "has_security_baseline": any(
                "SECURITY" in f.upper() or "security" in f for f in files
            ),
        }

    def _dependencies(self, files: list[str]) -> dict[str, Any]:
        found: dict[str, Any] = {"manifests": [], "packages": []}
        for name in _DEP_FILES:
            if name in files:
                found["manifests"].append(name)
                path = self.root / name
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")[:8000]
                except OSError:
                    continue
                if name == "requirements.txt":
                    pkgs = [
                        ln.strip().split("==")[0].split(">=")[0].split("[")[0]
                        for ln in text.splitlines()
                        if ln.strip() and not ln.strip().startswith("#")
                    ]
                    found["packages"].extend(pkgs[:80])
                elif name == "package.json":
                    try:
                        data = json.loads(text)
                        for section in ("dependencies", "devDependencies"):
                            found["packages"].extend(list((data.get(section) or {}).keys())[:80])
                    except json.JSONDecodeError:
                        pass
                elif name == "pyproject.toml":
                    for m in re.finditer(r'^\s*"([a-zA-Z0-9_.\-]+)"\s*[>=<]', text, re.M):
                        found["packages"].append(m.group(1))
        found["packages"] = sorted(set(found["packages"]))[:120]
        return found

    def _architecture_hints(self, files: list[str]) -> dict[str, Any]:
        kinds = []
        if any(f.endswith(".html") for f in files) and not any(f.endswith(".py") for f in files):
            kinds.append("static_website")
        if any(f.endswith((".tsx", ".jsx", ".vue")) for f in files) or "package.json" in files:
            kinds.append("frontend_application")
        if any("fastapi" in f.lower() or f.endswith("main.py") or f.startswith("app/") for f in files):
            kinds.append("backend_api")
        if any(f.endswith((".sql",)) or "migrations" in f for f in files):
            kinds.append("database_backed")
        if "Dockerfile" in files or any(f.startswith("deploy") for f in files):
            kinds.append("service_deployable")
        layers = []
        for marker, layer in (
            ("templates/", "presentation"),
            ("static/", "static_assets"),
            ("api/", "api"),
            ("app/", "application"),
            ("tests/", "tests"),
            ("migrations/", "data"),
            ("src/", "source"),
        ):
            if any(f.startswith(marker) or f"/{marker}" in f for f in files):
                layers.append(layer)
        return {
            "suggested_kinds": kinds or ["generic"],
            "layers": layers,
            "entrypoints": [
                f
                for f in files
                if f in ("index.html", "main.py", "app.py", "server.py", "manage.py", "src/index.js")
            ][:10],
        }
