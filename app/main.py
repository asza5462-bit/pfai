"""NOVA Code API — agentic AI software studio."""
from __future__ import annotations

import mimetypes
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
)
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import __version__, agent, provider, workspace
from app.auth import (
    COOKIE_NAME,
    current_user,
    login,
    logout,
    set_session_cookie,
    setup_owner,
    token_from,
    user_count,
)
from app.config import settings
from app.database import db

STATIC = Path(__file__).resolve().parent / "static"
User = Annotated[dict, Depends(current_user)]
_rate_buckets: dict[str, deque[float]] = defaultdict(deque)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.ensure_dirs()
    db.init()
    yield


app = FastAPI(
    title="NOVA Code",
    description="Agentic AI coding studio",
    version=__version__,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
)
app.mount("/assets", StaticFiles(directory=str(STATIC / "assets")), name="assets")


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    try:
        content_length = int(request.headers.get("content-length") or 0)
    except ValueError:
        return JSONResponse({"detail": "Content-Length غير صالح"}, status_code=400)
    if content_length > 2_500_000:
        return JSONResponse({"detail": "الطلب أكبر من الحد"}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-src 'self'"
    )
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def rate_limit(request: Request, name: str, limit: int, window: int) -> None:
    host = request.client.host if request.client else "unknown"
    key = f"{name}:{host}"
    now = time.monotonic()
    bucket = _rate_buckets[key]
    while bucket and bucket[0] < now - window:
        bucket.popleft()
    if len(bucket) >= limit:
        raise HTTPException(429, "طلبات كثيرة؛ حاول بعد قليل")
    bucket.append(now)


class SetupBody(BaseModel):
    username: str
    password: str
    setup_token: str = ""


class LoginBody(BaseModel):
    username: str
    password: str


class ProviderBody(BaseModel):
    provider: str = Field(pattern="^(openai|anthropic|compatible)$")
    model: str = Field(min_length=1, max_length=120)
    api_key: str | None = Field(default=None, max_length=500)
    base_url: str | None = Field(default=None, max_length=500)


class ProjectBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    template: str = Field(default="blank", pattern="^(blank|python|web)$")


class FileBody(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=1_100_000)
    expected_checksum: str | None = Field(default=None, min_length=64, max_length=64)


class DeleteFileBody(BaseModel):
    path: str = Field(min_length=1, max_length=500)


class CommandBody(BaseModel):
    command: str = Field(min_length=1, max_length=1000)


class CheckpointBody(BaseModel):
    message: str = Field(default="NOVA checkpoint", min_length=1, max_length=120)


class RestoreBody(BaseModel):
    revision_id: int = Field(gt=0)


class ConversationBody(BaseModel):
    title: str = Field(default="محادثة جديدة", max_length=100)


class ChatBody(BaseModel):
    conversation_id: str = Field(min_length=16, max_length=64)
    message: str = Field(min_length=1, max_length=50_000)
    selected_file: str | None = Field(default=None, max_length=500)
    auto_apply: bool = True
    allow_commands: bool = False


@app.api_route("/", methods=["GET", "HEAD"])
async def index():
    return FileResponse(STATIC / "index.html")


@app.api_route("/health", methods=["GET", "HEAD"])
@app.api_route("/healthz", methods=["GET", "HEAD"])
async def health():
    return {
        "ok": True,
        "name": "NOVA Code",
        "version": __version__,
        "service": os.getenv("RENDER_SERVICE_NAME", "local"),
        "configured": settings.production_ready,
    }


@app.api_route("/health/live", methods=["GET", "HEAD"])
async def health_live():
    return {"ok": True, "status": "live"}


@app.api_route("/health/ready", methods=["GET", "HEAD"])
async def health_ready():
    try:
        row = db.one("SELECT 1 AS ready")
        ready = bool(row and row["ready"] == 1)
    except Exception:  # noqa: BLE001 - readiness must report failure instead of crashing
        ready = False
    if not ready:
        raise HTTPException(503, "database_not_ready")
    return {"ok": True, "status": "ready"}


@app.get("/api/info")
async def info():
    return {
        "ok": True,
        "name": "NOVA Code",
        "version": __version__,
        "capabilities": [
            "AI chat",
            "agentic code editing",
            "file workspace",
            "code search and file revisions",
            "project ZIP export",
            "safe command runner",
            "Git checkpoints",
            "OpenAI",
            "Anthropic",
            "OpenAI-compatible APIs",
        ],
    }


@app.get("/api/auth/status")
async def auth_status(
    request: Request,
    authorization: str | None = Header(default=None),
    nova_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
):
    user = None
    try:
        user = current_user(request, authorization, nova_session)
    except HTTPException:
        pass
    return {
        "ok": True,
        "authenticated": bool(user),
        "needs_setup": user_count() == 0,
        "setup_token_required": bool(settings.setup_token),
        "user": user,
    }


@app.post("/api/auth/setup")
async def auth_setup(body: SetupBody, response: Response, request: Request):
    rate_limit(request, "setup", 5, 300)
    result = setup_owner(body.username, body.password, body.setup_token)
    set_session_cookie(response, result.token)
    return {"ok": True, "user": result.user}


@app.post("/api/auth/login")
async def auth_login(body: LoginBody, response: Response, request: Request):
    rate_limit(request, "login", 10, 300)
    result = login(body.username, body.password)
    set_session_cookie(response, result.token)
    return {"ok": True, "user": result.user}


@app.post("/api/auth/logout")
async def auth_logout(
    response: Response,
    authorization: str | None = Header(default=None),
    nova_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
):
    logout(token_from(authorization, nova_session))
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@app.get("/api/provider")
async def get_provider(user: User):
    return {"ok": True, **provider.public_config(user["id"])}


@app.put("/api/provider")
async def set_provider(body: ProviderBody, user: User):
    return {"ok": True, **provider.save_config(user["id"], body.provider, body.model, body.api_key, body.base_url)}


@app.post("/api/provider/test")
async def test_provider(user: User, request: Request):
    rate_limit(request, "provider-test", 10, 300)
    return await provider.test_connection(user["id"])


@app.get("/api/projects")
async def projects(user: User):
    return {"ok": True, "projects": workspace.list_projects(user["id"])}


@app.post("/api/projects")
async def new_project(body: ProjectBody, user: User):
    return {"ok": True, "project": workspace.create_project(user["id"], body.name, body.description, body.template)}


@app.delete("/api/projects/{project_id}")
async def remove_project(project_id: str, user: User):
    workspace.delete_project(project_id, user["id"])
    return {"ok": True}


@app.get("/api/projects/{project_id}/tree")
async def project_tree(project_id: str, user: User):
    return {"ok": True, "tree": workspace.tree(project_id, user["id"])}


@app.get("/api/projects/{project_id}/file")
async def get_file(project_id: str, user: User, path: str = Query(..., max_length=500)):
    return {"ok": True, **workspace.read_file(project_id, user["id"], path)}


@app.put("/api/projects/{project_id}/file")
async def put_file(project_id: str, body: FileBody, user: User):
    return workspace.write_file(
        project_id,
        user["id"],
        body.path,
        body.content,
        expected_checksum=body.expected_checksum,
    )


@app.delete("/api/projects/{project_id}/file")
async def remove_file(project_id: str, body: DeleteFileBody, user: User):
    workspace.delete_file(project_id, user["id"], body.path)
    return {"ok": True}


@app.get("/api/projects/{project_id}/search")
async def project_search(
    project_id: str,
    user: User,
    q: str = Query(..., min_length=2, max_length=200),
    limit: int = Query(100, ge=1, le=300),
):
    return {"ok": True, "results": workspace.search_files(project_id, user["id"], q, limit)}


@app.get("/api/projects/{project_id}/revisions")
async def revisions(project_id: str, user: User, path: str = Query(..., max_length=500)):
    return {"ok": True, "revisions": workspace.file_revisions(project_id, user["id"], path)}


@app.post("/api/projects/{project_id}/restore")
async def restore(project_id: str, body: RestoreBody, user: User):
    return workspace.restore_revision(project_id, user["id"], body.revision_id)


@app.get("/api/projects/{project_id}/export")
async def export(project_id: str, user: User):
    filename, content = workspace.export_project(project_id, user["id"])
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@app.get("/api/projects/{project_id}/diff")
async def project_diff(project_id: str, user: User):
    return {"ok": True, "diff": workspace.git_diff(project_id, user["id"])}


@app.post("/api/projects/{project_id}/command")
async def command(project_id: str, body: CommandBody, user: User, request: Request):
    rate_limit(request, f"command:{user['id']}", 30, 60)
    return workspace.run_command(project_id, user["id"], body.command)


@app.post("/api/projects/{project_id}/checkpoint")
async def checkpoint(project_id: str, body: CheckpointBody, user: User):
    return workspace.git_checkpoint(project_id, user["id"], body.message)


@app.get("/api/projects/{project_id}/conversations")
async def conversation_list(project_id: str, user: User):
    return {"ok": True, "conversations": agent.conversations(project_id, user["id"])}


@app.post("/api/projects/{project_id}/conversations")
async def conversation_create(project_id: str, body: ConversationBody, user: User):
    return {"ok": True, "conversation": agent.create_conversation(project_id, user["id"], body.title)}


@app.get("/api/projects/{project_id}/conversations/{conversation_id}/messages")
async def message_list(project_id: str, conversation_id: str, user: User):
    return {"ok": True, "messages": agent.messages(conversation_id, project_id, user["id"])}


@app.post("/api/projects/{project_id}/chat")
async def chat(project_id: str, body: ChatBody, user: User, request: Request):
    rate_limit(request, f"chat:{user['id']}", 20, 300)
    return await agent.run_agent(
        project_id,
        user["id"],
        body.conversation_id,
        body.message,
        selected_file=body.selected_file,
        auto_apply=body.auto_apply,
        allow_commands=body.allow_commands,
    )


@app.get("/api/projects/{project_id}/preview/{path:path}")
async def preview(project_id: str, path: str, user: User):
    root = workspace.project_root(project_id, user["id"])
    target = workspace.safe_path(root, path or "index.html", must_exist=True)
    if not target.is_file():
        raise HTTPException(404, "ملف المعاينة غير موجود")
    media_type = mimetypes.guess_type(target.name)[0] or "text/plain"
    response = FileResponse(target, media_type=media_type)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self' data: blob:; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'"
    )
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response
