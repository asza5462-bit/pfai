#!/usr/bin/env python3
"""Apply email credentials from the production secret store and verify real OTP delivery.

Never prints secret values. Writes email_live_verify.json only on successful non-mock send.
Run after owner places SMTP/API credentials into /agent/pfai/runtime/production.env
(or the process environment).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRET_FILE = Path("/agent/pfai/runtime/production.env")
EVIDENCE = ROOT / "data" / "longevity" / "elite" / "email_live_verify.json"


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def main() -> int:
    sys.path.insert(0, str(ROOT))
    _load_env_file(SECRET_FILE)

    from pfai.email_provider import (
        EmailMessageSpec,
        email_config_report,
        email_provider_from_env,
    )
    from pfai.owner_auth import OwnerAuthService
    from pfai.owner_control import OwnerControl

    report = email_config_report()
    kind = report.get("EMAIL_PROVIDER")
    print(
        "EMAIL_PRECHECK",
        json.dumps(
            {
                "EMAIL_PROVIDER": kind,
                "EMAIL_DELIVERY_STATUS": report.get("EMAIL_DELIVERY_STATUS"),
                "host_configured": report.get("host_configured"),
                "endpoint_configured": report.get("endpoint_configured"),
                "from_configured": report.get("from_configured"),
                "api_key_configured": report.get("api_key_configured"),
            }
        ),
    )
    if kind not in ("smtp", "api"):
        print(
            "BLOCKER=EMAIL_CREDENTIALS "
            "ACTION=Set PFAI_EMAIL_PROVIDER=smtp (or api) plus credentials in "
            f"{SECRET_FILE} then re-run this script / restart the container."
        )
        return 2

    provider = email_provider_from_env(allow_mock=False)
    owner_email = (os.environ.get("PFAI_OWNER_EMAIL") or "").strip()
    if not owner_email:
        print("BLOCKER=PFAI_OWNER_EMAIL missing in secret store")
        return 2

    # Real delivery probe — body is a non-OTP canary (never log OTP).
    canary = f"PFAI email delivery verification {int(time.time())}"
    send = provider.send(
        EmailMessageSpec(
            to=owner_email,
            subject="PFAI production email delivery verification",
            body_text=canary,
        )
    )
    print(
        "SEND_RESULT",
        json.dumps({"ok": send.get("ok"), "provider": send.get("provider"), "error": send.get("error")}),
    )
    if not send.get("ok"):
        print("BLOCKER=EMAIL_SEND_FAILED ACTION=Fix SMTP/API credentials or provider reachability")
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

    # OTP path smoke (uniform response; does not echo OTP)
    auth = OwnerAuthService(OwnerControl(), email_provider=provider)
    otp_req = auth.request_email_otp(owner_email, client_key="prod-verify")
    print(
        "OTP_REQUEST",
        json.dumps(
            {
                "ok": otp_req.get("ok"),
                "has_challenge": bool(otp_req.get("challenge_id")),
                "message": otp_req.get("message"),
            }
        ),
    )
    final = email_config_report(provider)
    print(
        "EMAIL_FINAL",
        json.dumps(
            {
                "EMAIL_DELIVERY_STATUS": final.get("EMAIL_DELIVERY_STATUS"),
                "EMAIL_VERIFIED": final.get("EMAIL_VERIFIED"),
                "EMAIL_PRODUCTION_READY": final.get("EMAIL_PRODUCTION_READY"),
            }
        ),
    )
    return 0 if final.get("EMAIL_DELIVERY_STATUS") == "PRODUCTION_READY" else 4


if __name__ == "__main__":
    raise SystemExit(main())
