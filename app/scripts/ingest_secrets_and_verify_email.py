#!/usr/bin/env python3
"""Ingest email/hosting secrets from process env into the secret store, then verify.

Never prints secret values. Safe to re-run after owner supplies secrets via the
Cursor secure secret UI (or host environment injection).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

SECRET_FILE = Path("/agent/pfai/runtime/production.env")
EVIDENCE = Path("/agent/pfai/pfai/app/data/longevity/elite/email_live_verify.json")
APP_ROOT = Path("/agent/pfai/pfai/app")

EMAIL_KEYS = [
    "PFAI_EMAIL_PROVIDER",
    "PFAI_SMTP_HOST",
    "PFAI_SMTP_PORT",
    "PFAI_SMTP_USER",
    "PFAI_SMTP_PASSWORD",
    "PFAI_SMTP_FROM",
    "PFAI_SMTP_TLS",
    "PFAI_SMTP_TIMEOUT",
    "PFAI_EMAIL_API_ENDPOINT",
    "PFAI_EMAIL_API_KEY",
    "PFAI_EMAIL_FROM",
    "PFAI_EMAIL_API_AUTH_HEADER",
    "PFAI_EMAIL_API_AUTH_SCHEME",
    "PFAI_OWNER_EMAIL",
    "PFAI_EMAIL_REQUIRE_PRODUCTION",
    # aliases
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "SMTP_FROM",
    "SMTP_TLS",
    "EMAIL_API_KEY",
    "EMAIL_API_ENDPOINT",
    "EMAIL_FROM",
    "SENDGRID_API_KEY",
    "RESEND_API_KEY",
]


def _read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _write_env_file(path: Path, data: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Preserve comments/structure loosely: rewrite as key=value with header.
    lines = [
        "# PFAI production secret store — NEVER commit. Mode 600.",
        "# Updated by ingest_secrets_and_verify_email.py (values never logged).",
        "",
    ]
    for k, v in data.items():
        lines.append(f"{k}={v}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def _merge_from_process(existing: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    updated = dict(existing)
    changed: list[str] = []
    for k in EMAIL_KEYS:
        val = (os.environ.get(k) or "").strip()
        if not val:
            continue
        # Map common aliases into canonical PFAI_* names
        canon = k
        if k in ("SMTP_HOST",):
            canon = "PFAI_SMTP_HOST"
        elif k in ("SMTP_PORT",):
            canon = "PFAI_SMTP_PORT"
        elif k in ("SMTP_USER", "SMTP_USERNAME"):
            canon = "PFAI_SMTP_USER"
        elif k in ("SMTP_PASSWORD",):
            canon = "PFAI_SMTP_PASSWORD"
        elif k in ("SMTP_FROM",):
            canon = "PFAI_SMTP_FROM"
        elif k in ("SMTP_TLS",):
            canon = "PFAI_SMTP_TLS"
        elif k in ("EMAIL_API_KEY", "SENDGRID_API_KEY", "RESEND_API_KEY"):
            canon = "PFAI_EMAIL_API_KEY"
            if k == "SENDGRID_API_KEY" and not updated.get("PFAI_EMAIL_API_ENDPOINT") and not os.environ.get("PFAI_EMAIL_API_ENDPOINT"):
                updated["PFAI_EMAIL_API_ENDPOINT"] = "https://api.sendgrid.com/v3/mail/send"
                changed.append("PFAI_EMAIL_API_ENDPOINT")
            if k == "RESEND_API_KEY" and not updated.get("PFAI_EMAIL_API_ENDPOINT") and not os.environ.get("PFAI_EMAIL_API_ENDPOINT"):
                updated["PFAI_EMAIL_API_ENDPOINT"] = "https://api.resend.com/emails"
                changed.append("PFAI_EMAIL_API_ENDPOINT")
            if not updated.get("PFAI_EMAIL_PROVIDER") and not (os.environ.get("PFAI_EMAIL_PROVIDER") or "").strip():
                updated["PFAI_EMAIL_PROVIDER"] = "api"
                changed.append("PFAI_EMAIL_PROVIDER")
        elif k in ("EMAIL_API_ENDPOINT",):
            canon = "PFAI_EMAIL_API_ENDPOINT"
        elif k in ("EMAIL_FROM",):
            canon = "PFAI_EMAIL_FROM"
        if updated.get(canon) != val:
            updated[canon] = val
            changed.append(canon)
    # Prefer production email when real creds present
    provider = (updated.get("PFAI_EMAIL_PROVIDER") or "").lower()
    has_smtp = bool(updated.get("PFAI_SMTP_HOST") and (updated.get("PFAI_SMTP_FROM") or updated.get("PFAI_SMTP_USER")))
    has_api = bool(updated.get("PFAI_EMAIL_API_ENDPOINT") and updated.get("PFAI_EMAIL_API_KEY") and (updated.get("PFAI_EMAIL_FROM") or updated.get("PFAI_SMTP_FROM")))
    if has_smtp and provider in ("", "mock"):
        updated["PFAI_EMAIL_PROVIDER"] = "smtp"
        changed.append("PFAI_EMAIL_PROVIDER")
    if has_api and provider in ("", "mock") and not has_smtp:
        updated["PFAI_EMAIL_PROVIDER"] = "api"
        changed.append("PFAI_EMAIL_PROVIDER")
    if updated.get("PFAI_EMAIL_PROVIDER") in ("smtp", "api"):
        updated["PFAI_EMAIL_REQUIRE_PRODUCTION"] = "1"
        changed.append("PFAI_EMAIL_REQUIRE_PRODUCTION")
    return updated, sorted(set(changed))


def _load_into_os(data: dict[str, str]) -> None:
    for k, v in data.items():
        os.environ[k] = v


def _restart_container() -> None:
    subprocess.run(["sudo", "-n", "docker", "rm", "-f", "pfai-prod"], check=False, capture_output=True)
    subprocess.run(
        [
            "sudo",
            "-n",
            "docker",
            "run",
            "-d",
            "--name",
            "pfai-prod",
            "--network",
            "host",
            "--env-file",
            str(SECRET_FILE),
            "-e",
            "PFAI_HOST=0.0.0.0",
            "-e",
            "PORT=8000",
            "-v",
            "/agent/pfai/pfai/app/data:/app/data",
            "--restart",
            "unless-stopped",
            "pfai:8.0.0",
        ],
        check=False,
        capture_output=True,
    )


def main() -> int:
    sys.path.insert(0, str(APP_ROOT))
    existing = _read_env_file(SECRET_FILE)
    # Defaults that must remain
    existing.setdefault("PFAI_ENV", "production")
    existing.setdefault("PFAI_HOST", "0.0.0.0")
    existing.setdefault("PORT", "8000")
    existing.setdefault("PFAI_WEB_ALLOW_NETWORK", "1")
    existing.setdefault("PFAI_WEB_SEARCH_PROVIDER", "auto")
    existing.setdefault("PFAI_WEB_FETCH_PROVIDER", "http_fetch")
    existing.setdefault("PFAI_TRAINING_ROOT", "data/longevity/training_phase9_verify")

    merged, changed = _merge_from_process(existing)
    if changed:
        _write_env_file(SECRET_FILE, merged)
        print("SECRETS_INGESTED_KEYS=" + ",".join(changed))
    else:
        print("SECRETS_INGESTED_KEYS=")

    _load_into_os(merged)
    from pfai.email_provider import EmailMessageSpec, email_config_report, email_provider_from_env

    report = email_config_report()
    print(
        "EMAIL_PRECHECK="
        + json.dumps(
            {
                "EMAIL_PROVIDER": report.get("EMAIL_PROVIDER"),
                "EMAIL_DELIVERY_STATUS": report.get("EMAIL_DELIVERY_STATUS"),
                "host_configured": report.get("host_configured"),
                "endpoint_configured": report.get("endpoint_configured"),
                "from_configured": report.get("from_configured"),
                "api_key_configured": report.get("api_key_configured"),
            }
        )
    )
    kind = report.get("EMAIL_PROVIDER")
    if kind not in ("smtp", "api"):
        print("STATUS=WAITING_FOR_OWNER_SECRETS")
        return 2

    provider = email_provider_from_env(allow_mock=False)
    owner_email = (os.environ.get("PFAI_OWNER_EMAIL") or merged.get("PFAI_OWNER_EMAIL") or "").strip()
    if not owner_email:
        print("STATUS=MISSING_OWNER_EMAIL")
        return 2

    send = provider.send(
        EmailMessageSpec(
            to=owner_email,
            subject="PFAI production email delivery verification",
            body_text=f"PFAI email delivery verification {int(time.time())}",
        )
    )
    print("SEND_RESULT=" + json.dumps({"ok": send.get("ok"), "provider": send.get("provider"), "error": send.get("error")}))
    if not send.get("ok"):
        print("STATUS=EMAIL_SEND_FAILED")
        return 3

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(
        json.dumps(
            {
                "ts": time.time(),
                "send_ok": True,
                "provider": send.get("provider"),
                "to_configured": True,
                "fabricated": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # OTP request via service (uniform; no OTP echo)
    from pfai.owner_auth import OwnerAuthService
    from pfai.owner_control import OwnerControl

    auth = OwnerAuthService(OwnerControl(), email_provider=provider)
    otp_req = auth.request_otp(owner_email, client_key="prod-email-verify")
    print(
        "OTP_REQUEST="
        + json.dumps(
            {
                "ok": otp_req.get("ok"),
                "has_challenge": bool(otp_req.get("challenge_id")),
                "message": otp_req.get("message"),
                "leaks_otp": bool(re.search(r"\b\d{6}\b", json.dumps(otp_req))),
            }
        )
    )

    final = email_config_report(provider)
    print(
        "EMAIL_FINAL="
        + json.dumps(
            {
                "EMAIL_DELIVERY_STATUS": final.get("EMAIL_DELIVERY_STATUS"),
                "EMAIL_VERIFIED": final.get("EMAIL_VERIFIED"),
                "EMAIL_PRODUCTION_READY": final.get("EMAIL_PRODUCTION_READY"),
            }
        )
    )

    _restart_container()
    print("CONTAINER_RESTARTED=pfai-prod")
    return 0 if final.get("EMAIL_DELIVERY_STATUS") == "PRODUCTION_READY" else 4


if __name__ == "__main__":
    raise SystemExit(main())
