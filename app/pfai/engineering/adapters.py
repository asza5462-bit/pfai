"""PHASE 18 Application Engineering adapters — claim only implemented project types."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pfai.engineering.project_workspace import ProjectWorkspace
from pfai.engineering.templates import materialize_template
from pfai.engineering.types import ProjectKind


class ProjectAdapter(ABC):
    """Adapter interface for generating a project skeleton into a workspace."""

    adapter_id: str = "base"
    version: str = "1.0.0"
    languages: tuple[str, ...] = ()
    frameworks: tuple[str, ...] = ()
    project_kinds: tuple[str, ...] = ()

    @abstractmethod
    def matches(self, requirement: str, *, kind: str = "") -> bool:
        raise NotImplementedError

    @abstractmethod
    def materialize(
        self,
        workspace: ProjectWorkspace,
        *,
        name: str,
        description: str,
        kind: str,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def capabilities(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "version": self.version,
            "languages": list(self.languages),
            "frameworks": list(self.frameworks),
            "project_kinds": list(self.project_kinds),
        }


class StaticWebsiteAdapter(ProjectAdapter):
    adapter_id = "static_website"
    languages = ("html", "css", "javascript")
    frameworks = ()
    project_kinds = (ProjectKind.STATIC_WEBSITE.value,)

    def matches(self, requirement: str, *, kind: str = "") -> bool:
        if kind == ProjectKind.STATIC_WEBSITE.value:
            return True
        t = (requirement or "").lower()
        return any(w in t for w in ("static site", "landing page", "static website", "html website"))

    def materialize(self, workspace: ProjectWorkspace, *, name: str, description: str, kind: str) -> dict[str, Any]:
        return materialize_template(workspace, kind=ProjectKind.STATIC_WEBSITE.value, name=name, description=description)


class FastAPIAdapter(ProjectAdapter):
    adapter_id = "fastapi_python"
    languages = ("python",)
    frameworks = ("fastapi",)
    project_kinds = (ProjectKind.BACKEND_API.value, ProjectKind.SERVICE_API.value)

    def matches(self, requirement: str, *, kind: str = "") -> bool:
        if kind in self.project_kinds:
            return True
        t = (requirement or "").lower()
        return any(w in t for w in ("fastapi", "rest api", "backend api", "python api"))

    def materialize(self, workspace: ProjectWorkspace, *, name: str, description: str, kind: str) -> dict[str, Any]:
        use = kind if kind in self.project_kinds else ProjectKind.BACKEND_API.value
        return materialize_template(workspace, kind=use, name=name, description=description)


class NodeRestAdapter(ProjectAdapter):
    adapter_id = "nodejs_rest"
    languages = ("javascript", "typescript")
    frameworks = ("nodejs",)
    project_kinds = (ProjectKind.SERVICE_API.value, ProjectKind.BACKEND_API.value)

    def matches(self, requirement: str, *, kind: str = "") -> bool:
        t = (requirement or "").lower()
        return any(w in t for w in ("node.js", "nodejs", "express", "typescript api", "javascript api"))

    def materialize(self, workspace: ProjectWorkspace, *, name: str, description: str, kind: str) -> dict[str, Any]:
        # Node/Express skeleton — implemented files, not a fake claim
        files = {
            "package.json": f'''{{
  "name": "{name}",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {{"test": "node --test tests/test_health.mjs"}},
  "description": "{description[:120]}"
}}
''',
            "src/server.mjs": '''/** Minimal Node HTTP API — secrets via process.env only. */
import http from "node:http";

const PORT = Number(process.env.PORT || 0);

export function health() {
  return { ok: true, env: process.env.APP_ENV || "development" };
}

export function createServer() {
  return http.createServer((req, res) => {
    if (req.url === "/health") {
      res.writeHead(200, {
        "content-type": "application/json",
        "x-content-type-options": "nosniff",
      });
      res.end(JSON.stringify(health()));
      return;
    }
    res.writeHead(404, { "content-type": "application/json" });
    res.end(JSON.stringify({ ok: false, error: "not_found" }));
  });
}

if (PORT > 0) {
  createServer().listen(PORT);
}
''',
            "tests/test_health.mjs": '''import test from "node:test";
import assert from "node:assert/strict";
import { health } from "../src/server.mjs";

test("health ok", () => {
  assert.equal(health().ok, true);
});
''',
            "tests/test_structure.py": """from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def test_node_files():
    assert (ROOT / 'package.json').exists()
    assert (ROOT / 'src' / 'server.mjs').exists()
""",
        }
        written = []
        for rel, body in files.items():
            r = workspace.write_text(rel, body, overwrite=False)
            if not r.get("ok"):
                return {"ok": False, "error": r.get("error"), "path": rel}
            written.append(rel)
        # Shared baseline docs via template helper path
        base = materialize_template(
            workspace,
            kind=ProjectKind.SERVICE_API.value,
            name=name,
            description=description or "Node.js REST API skeleton",
        )
        # Prefer Node files; service template also wrote service/ — keep both for structure tests
        return {
            "ok": True,
            "kind": "nodejs_rest",
            "adapter_id": self.adapter_id,
            "files": written + list(base.get("files") or []),
            "tests": [f for f in written if "test" in f],
        }


class ReactFrontendAdapter(ProjectAdapter):
    adapter_id = "react_frontend"
    languages = ("javascript", "typescript")
    frameworks = ("react",)
    project_kinds = (ProjectKind.FRONTEND_APP.value,)

    def matches(self, requirement: str, *, kind: str = "") -> bool:
        if kind == ProjectKind.FRONTEND_APP.value:
            return True
        t = (requirement or "").lower()
        return "react" in t and "next" not in t

    def materialize(self, workspace: ProjectWorkspace, *, name: str, description: str, kind: str) -> dict[str, Any]:
        files = {
            "package.json": f'''{{
  "name": "{name}",
  "version": "0.1.0",
  "private": true,
  "dependencies": {{"react": "^18.2.0", "react-dom": "^18.2.0"}}
}}
''',
            "src/App.jsx": f'''export default function App() {{
  return (
    <main>
      <h1>{name}</h1>
      <p>{description[:200] or "React frontend skeleton"}</p>
    </main>
  );
}}
''',
            "src/index.jsx": '''import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";

const el = document.getElementById("root");
if (el) createRoot(el).render(<App />);
''',
            "index.html": f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta http-equiv="Content-Security-Policy" content="default-src 'self'"/>
<title>{name}</title></head>
<body><div id="root"></div><script type="module" src="/src/index.jsx"></script></body></html>
''',
            "tests/test_react_structure.py": """from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def test_react_files():
    assert (ROOT / 'src' / 'App.jsx').exists()
    assert 'Content-Security-Policy' in (ROOT / 'index.html').read_text(encoding='utf-8')
""",
        }
        written = []
        for rel, body in files.items():
            r = workspace.write_text(rel, body, overwrite=False)
            if not r.get("ok"):
                return {"ok": False, "error": r.get("error"), "path": rel}
            written.append(rel)
        materialize_template(workspace, kind=ProjectKind.FRONTEND_APP.value, name=name, description=description)
        return {"ok": True, "kind": "react_frontend", "adapter_id": self.adapter_id, "files": written, "tests": [f for f in written if f.startswith("tests/")]}


class NextJsAdapter(ProjectAdapter):
    adapter_id = "nextjs"
    languages = ("javascript", "typescript")
    frameworks = ("nextjs", "react")
    project_kinds = (ProjectKind.FULLSTACK.value, ProjectKind.FRONTEND_APP.value)

    def matches(self, requirement: str, *, kind: str = "") -> bool:
        t = (requirement or "").lower()
        return "next.js" in t or "nextjs" in t

    def materialize(self, workspace: ProjectWorkspace, *, name: str, description: str, kind: str) -> dict[str, Any]:
        files = {
            "package.json": f'''{{
  "name": "{name}",
  "version": "0.1.0",
  "private": true,
  "scripts": {{"dev": "echo next_dev_placeholder", "test": "python -m pytest tests -q"}},
  "dependencies": {{"next": "^14.0.0", "react": "^18.2.0", "react-dom": "^18.2.0"}}
}}
''',
            "app/page.jsx": f'''export default function Page() {{
  return (
    <main>
      <h1>{name}</h1>
      <p>{description[:200] or "Next.js app router skeleton"}</p>
    </main>
  );
}}
''',
            "app/layout.jsx": f'''export const metadata = {{ title: "{name}" }};
export default function RootLayout({{ children }}) {{
  return (
    <html lang="en">
      <head>
        <meta httpEquiv="Content-Security-Policy" content="default-src 'self'" />
      </head>
      <body>{{children}}</body>
    </html>
  );
}}
''',
            "tests/test_next_structure.py": """from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def test_next_files():
    assert (ROOT / 'app' / 'page.jsx').exists()
    assert (ROOT / 'package.json').exists()
""",
        }
        written = []
        for rel, body in files.items():
            r = workspace.write_text(rel, body, overwrite=False)
            if not r.get("ok"):
                return {"ok": False, "error": r.get("error"), "path": rel}
            written.append(rel)
        return {"ok": True, "kind": "nextjs", "adapter_id": self.adapter_id, "files": written, "tests": [f for f in written if f.startswith("tests/")]}


class DatabaseBackedAdapter(ProjectAdapter):
    adapter_id = "database_backed"
    languages = ("python", "sql")
    frameworks = ("sqlite",)
    project_kinds = (ProjectKind.DATABASE_BACKED.value,)

    def matches(self, requirement: str, *, kind: str = "") -> bool:
        if kind == ProjectKind.DATABASE_BACKED.value:
            return True
        t = (requirement or "").lower()
        return any(w in t for w in ("database", "schema", "migration", "sql"))

    def materialize(self, workspace: ProjectWorkspace, *, name: str, description: str, kind: str) -> dict[str, Any]:
        return materialize_template(workspace, kind=ProjectKind.DATABASE_BACKED.value, name=name, description=description)


class FullStackAdapter(ProjectAdapter):
    adapter_id = "fullstack"
    languages = ("python", "javascript", "html", "sql")
    frameworks = ("fastapi",)
    project_kinds = (ProjectKind.FULLSTACK.value,)

    def matches(self, requirement: str, *, kind: str = "") -> bool:
        if kind == ProjectKind.FULLSTACK.value:
            return True
        t = (requirement or "").lower()
        return any(w in t for w in ("full-stack", "fullstack", "full stack", "website and api"))

    def materialize(self, workspace: ProjectWorkspace, *, name: str, description: str, kind: str) -> dict[str, Any]:
        return materialize_template(workspace, kind=ProjectKind.FULLSTACK.value, name=name, description=description)


# Registry of actually implemented adapters
IMPLEMENTED_ADAPTERS: list[ProjectAdapter] = [
    NextJsAdapter(),
    ReactFrontendAdapter(),
    NodeRestAdapter(),
    FastAPIAdapter(),
    FullStackAdapter(),
    DatabaseBackedAdapter(),
    StaticWebsiteAdapter(),
]


def list_supported_adapters() -> list[dict[str, Any]]:
    return [a.capabilities() for a in IMPLEMENTED_ADAPTERS]


def select_adapter(requirement: str, *, kind: str = "") -> ProjectAdapter:
    for adapter in IMPLEMENTED_ADAPTERS:
        if adapter.matches(requirement, kind=kind):
            return adapter
    # Default: static website (always implemented)
    return StaticWebsiteAdapter()
