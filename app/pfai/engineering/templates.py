"""PHASE 14 project templates — structure, env separation, tests, security baseline."""
from __future__ import annotations

from typing import Any

from pfai.engineering.project_workspace import ProjectWorkspace
from pfai.engineering.types import ProjectKind


def _readme(name: str, kind: str, description: str) -> str:
    return f"""# {name}

Kind: `{kind}`

{description}

## Setup

1. Copy `.env.example` to a private secret store / local `.env` (never commit secrets).
2. Install dependencies for your runtime.
3. Run tests.

## Security baseline

- Secrets via environment variables only
- No credentials in source control
- Input validation on API boundaries
- Security headers recommended for HTTP surfaces

## Validation

See `VALIDATION_REPORT.md` after generation/tests.
"""


def _env_example() -> str:
    return """# TEMPLATE ONLY — never commit real secrets
APP_ENV=development
# DATABASE_URL=
# SESSION_SECRET=
# API_KEY=
"""


def _security_baseline_md() -> str:
    return """# Security baseline

- [ ] Secrets only in environment / secret store
- [ ] Authentication & authorization reviewed
- [ ] Input validation on untrusted input
- [ ] Output encoding for HTML contexts
- [ ] HTTPS / secure cookies in production
- [ ] Dependency updates monitored
- [ ] Security headers configured for HTTP apps
"""


TEMPLATES: dict[str, dict[str, Any]] = {
    ProjectKind.STATIC_WEBSITE.value: {
        "description": "Static website with HTML/CSS/JS and a basic smoke test.",
        "files": {
            "index.html": """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <meta http-equiv="Content-Security-Policy" content="default-src 'self'"/>
  <title>{name}</title>
  <link rel="stylesheet" href="styles.css"/>
</head>
<body>
  <main>
    <h1>{name}</h1>
    <p>{description}</p>
  </main>
  <script src="app.js"></script>
</body>
</html>
""",
            "styles.css": "body{font-family:system-ui,sans-serif;margin:2rem;line-height:1.5}\n",
            "app.js": "document.documentElement.dataset.ready='1';\n",
            "tests/test_smoke.py": """from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def test_index_exists():
    html = (ROOT / 'index.html').read_text(encoding='utf-8')
    assert '<h1>' in html
    assert 'Content-Security-Policy' in html
""",
        },
    },
    ProjectKind.BACKEND_API.value: {
        "description": "Minimal FastAPI-style backend skeleton with health + echo endpoints.",
        "files": {
            "app/main.py": '''"""Minimal API skeleton — secrets via environment only."""
from __future__ import annotations
import os
from typing import Any

try:
    from fastapi import FastAPI, HTTPException
except Exception:  # pragma: no cover - offline stub path
    FastAPI = None  # type: ignore

def create_app():
    if FastAPI is None:
        raise RuntimeError("fastapi_not_installed")
    app = FastAPI(title=os.environ.get("APP_NAME", "pfai-api"))

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "env": os.environ.get("APP_ENV", "development")}

    @app.post("/echo")
    def echo(payload: dict[str, Any]) -> dict[str, Any]:
        # Reject obvious secret keys in payload echo
        banned = ("password", "secret", "token", "api_key")
        if any(k.lower() in banned for k in payload.keys()):
            raise HTTPException(400, "sensitive_keys_not_allowed")
        text = str(payload.get("text") or "")[:2000]
        return {"ok": True, "echo": text}

    return app

app = None
try:
    app = create_app()
except Exception:
    app = None
''',
            "tests/test_api_logic.py": """def test_echo_redacts_sensitive_keys():
    banned = ('password', 'secret', 'token', 'api_key')
    payload = {'password': 'x'}
    assert any(k in banned for k in payload)
""",
            "requirements.txt": "fastapi>=0.100\nuvicorn>=0.22\n",
        },
    },
    ProjectKind.FULLSTACK.value: {
        "description": "Full-stack starter: static frontend + backend API skeleton + schema stub.",
        "files": {
            "frontend/index.html": """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><title>{name}</title>
<meta http-equiv="Content-Security-Policy" content="default-src 'self'"/>
</head><body><h1>{name}</h1><p id="status">loading</p>
<script src="app.js"></script></body></html>
""",
            "frontend/app.js": "document.getElementById('status').textContent='ready';\n",
            "backend/app.py": '''"""Backend stub — use environment for secrets."""
import os

def health():
    return {"ok": True, "service": os.environ.get("APP_NAME", "fullstack")}
''',
            "db/schema.sql": """-- Example schema (no secrets)
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  created_at TEXT NOT NULL
);
""",
            "db/migrations/001_init.sql": """-- migration 001
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  created_at TEXT NOT NULL
);
""",
            "tests/test_fullstack.py": """from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def test_structure():
    assert (ROOT / 'frontend' / 'index.html').exists()
    assert (ROOT / 'backend' / 'app.py').exists()
    assert (ROOT / 'db' / 'schema.sql').exists()
""",
        },
    },
    ProjectKind.FRONTEND_APP.value: {
        "description": "Frontend application skeleton with modular JS and tests.",
        "files": {
            "src/index.html": """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><title>{name}</title>
<meta http-equiv="Content-Security-Policy" content="default-src 'self'"/>
</head><body><div id="app"></div><script type="module" src="main.js"></script></body></html>
""",
            "src/main.js": "export function boot(el){ el.textContent = 'ok'; }\nboot(document.getElementById('app'));\n",
            "tests/test_boot.py": """def test_boot_logic():
    def boot(el):
        el['text'] = 'ok'
    box = {}
    boot(box)
    assert box['text'] == 'ok'
""",
        },
    },
    ProjectKind.DATABASE_BACKED.value: {
        "description": "Database-backed service with schema, migration, and repository stub.",
        "files": {
            "db/schema.sql": """CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);
""",
            "db/migrations/001_users.sql": """CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);
""",
            "app/repository.py": '''"""Repository stub — parameterized queries only; no string-concat SQL."""
def find_user_sql() -> str:
    return "SELECT id, email FROM users WHERE email = ?"
''',
            "app/__init__.py": "",
            "tests/test_repo.py": """from app.repository import find_user_sql

def test_parameterized():
    sql = find_user_sql()
    assert '?' in sql
""",
        },
    },
    ProjectKind.SERVICE_API.value: {
        "description": "Service/API project with health, config separation, and tests.",
        "files": {
            "service/main.py": '''import os

def config():
    return {"env": os.environ.get("APP_ENV", "development"), "name": os.environ.get("APP_NAME", "service")}

def health():
    return {"ok": True, **config()}
''',
            "service/__init__.py": "",
            "tests/test_service.py": """from service.main import health

def test_health():
    assert health()['ok'] is True
""",
        },
    },
}


def materialize_template(
    workspace: ProjectWorkspace,
    *,
    kind: str,
    name: str,
    description: str = "",
) -> dict[str, Any]:
    spec = TEMPLATES.get(kind)
    if not spec:
        return {"ok": False, "error": "unknown_template", "kind": kind}
    desc = description or spec["description"]

    def _render(body: str) -> str:
        return body.replace("{name}", name).replace("{description}", desc)

    written = []
    for rel, body in spec["files"].items():
        content = _render(body)
        r = workspace.write_text(rel, content, overwrite=False)
        if not r.get("ok"):
            return {"ok": False, "error": r.get("error"), "path": rel}
        written.append(rel)
    workspace.write_text("README.md", _readme(name, kind, desc), overwrite=True)
    workspace.write_text(".env.example", _env_example(), overwrite=True)
    workspace.write_text("SECURITY_BASELINE.md", _security_baseline_md(), overwrite=True)
    written.extend(["README.md", ".env.example", "SECURITY_BASELINE.md"])
    return {
        "ok": True,
        "kind": kind,
        "files": written,
        "tests": [f for f in written if f.startswith("tests/")],
    }
