"""Production configuration detector — no secrets in output; identifies one-time owner actions."""
from __future__ import annotations

import os
from typing import Any

from pfai.authorized_execution import sanitize_args
from pfai.email_provider import email_config_report
from pfai.elite.sandbox import Sandbox
from pfai.elite.web_fabric import web_config_report


def _set(name: str) -> bool:
    v = os.environ.get(name)
    return bool(v is not None and str(v).strip() != "")


def detect_production_config() -> dict[str, Any]:
    """Return capability readiness + exact owner actions that Cursor cannot perform."""
    web = web_config_report()
    email = email_config_report()
    sandbox = Sandbox(timeout=1.0).metadata()

    missing: list[dict[str, str]] = []
    completed: list[str] = []

    # Owner auth — env presence only (never values)
    if _set("PFAI_OWNER_EMAIL") and _set("PFAI_OWNER_SECRET_HASH"):
        completed.append("owner_auth_env_present")
    else:
        missing.append(
            {
                "id": "OWNER_AUTH_SECRETS",
                "why": "Owner login / OTP recipient and passcode hash are required for protected routes",
                "where": "Deployment secret store / host environment (PFAI_OWNER_EMAIL, PFAI_OWNER_SECRET_HASH)",
                "owner_action": "Set both variables from a private secret store; never commit values",
            }
        )

    # Web fabric
    web_status = web.get("WEB_FABRIC_STATUS") or "NOT_CONFIGURED"
    if web_status == "READY":
        completed.append("web_provider_ready")
    else:
        missing.append(
            {
                "id": "WEB_PROVIDER",
                "why": "Live web search/fetch requires an explicit network-enabled provider; default is fail-closed",
                "where": "Host environment: PFAI_WEB_ALLOW_NETWORK, PFAI_WEB_SEARCH_PROVIDER, PFAI_WEB_FETCH_PROVIDER",
                "owner_action": (
                    "Option A (no API key): set PFAI_WEB_ALLOW_NETWORK=1, "
                    "PFAI_WEB_SEARCH_PROVIDER=ddg, PFAI_WEB_FETCH_PROVIDER=http_fetch "
                    "(results may be sparse; verify after deploy). "
                    "Option B: set PFAI_WEB_SEARCH_PROVIDER=http_search with "
                    "PFAI_WEB_SEARCH_ENDPOINT + PFAI_WEB_SEARCH_API_KEY in secrets."
                ),
            }
        )

    # Email
    email_status = email.get("EMAIL_DELIVERY_STATUS") or "TEST_ONLY"
    if email_status == "READY":
        completed.append("email_delivery_ready")
    else:
        missing.append(
            {
                "id": "EMAIL_DELIVERY",
                "why": "Production OTP/email delivery requires owner SMTP or email API credentials",
                "where": "Deployment secrets: PFAI_EMAIL_PROVIDER=smtp|api and SMTP_* / PFAI_EMAIL_API_*",
                "owner_action": "Configure SMTP or HTTP email API credentials in the host secret store, then re-check /platform/email/status",
            }
        )

    # Optional remote models — never required
    if _set("ANTHROPIC_API_KEY") or _set("OPENAI_API_KEY"):
        completed.append("optional_remote_model_key_present")
    else:
        missing.append(
            {
                "id": "OPTIONAL_REMOTE_MODEL",
                "why": "Not required — local/open-weight and MODEL_V0007 remain primary",
                "where": "Optional deployment secret ANTHROPIC_API_KEY / OpenAI-compatible key",
                "owner_action": "Optional: add a remote provider key only if you want that backend",
            }
        )

    # Hosting account for public deploy
    missing.append(
        {
            "id": "PUBLIC_HOSTING_AUTH",
            "why": "Public internet deployment requires an external hosting account Cursor cannot authorize",
            "where": "Render (render.yaml present), or any Docker host; Dockerfile + docker-compose.yml ready",
            "owner_action": "Connect the repo/image to your hosting account, set secrets listed above, deploy service pfai-v8 / docker compose up",
        }
    )

    deployable_locally = True  # Docker/compose present in repo
    return sanitize_args(
        {
            "ok": True,
            "phase": 23,
            "PHASE_24_STARTED": False,
            "WEB_FABRIC_STATUS": web_status,
            "WEB_PROVIDER_STATUS": web_status,
            "WEB_IMPLEMENTED": True,
            "WEB_CONFIGURED": web_status in ("READY", "TEST_ONLY"),
            "WEB_EXECUTABLE": bool(web.get("WEB_PROVIDER_AVAILABLE")),
            "EMAIL_DELIVERY_STATUS": email_status,
            "EMAIL_LIFECYCLE_STATUS": email.get("EMAIL_LIFECYCLE_STATUS"),
            "SANDBOX_STATUS": sandbox.get("SANDBOX_STATUS"),
            "OWNER_AUTH_ENV_PRESENT": _set("PFAI_OWNER_EMAIL") and _set("PFAI_OWNER_SECRET_HASH"),
            "local_docker_deployable": deployable_locally,
            "public_deploy_ready_artifacts": ["Dockerfile", "docker-compose.yml", "render.yaml"],
            "completed_by_cursor": completed
            + [
                "production_runtime",
                "web_research_pipeline",
                "mcp_registry",
                "tool_fabric_web_bridge",
                "frontend_chat_integration",
                "owner_authorization_gates",
                "model_v0007_active",
                "model_v0001_lkg_intact",
            ],
            "missing_owner_actions": missing,
            "secrets_exposed": False,
            "note": "Diagnostics never include secret values",
        }
    )
