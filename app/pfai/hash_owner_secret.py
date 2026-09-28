"""CLI helper: hash an owner password from stdin for env configuration.

Never commit the output into Git. Paste the hash into platform secrets only
(Render: PFAI_OWNER_SECRET_HASH).

Usage:
  python -m pfai.hash_owner_secret
  # type password (hidden), Enter
"""
from __future__ import annotations

import getpass
import sys

from pfai.owner_auth import OwnerAuthService


def main() -> int:
    try:
        secret = getpass.getpass("Owner password (input hidden): ")
    except Exception:
        secret = sys.stdin.readline().rstrip("\n")
    if not secret:
        print("empty password", file=sys.stderr)
        return 2
    if not OwnerAuthService.passcode_strong(secret):
        print(
            "weak password: use >=12 chars with mixed upper/lower/digit/symbol",
            file=sys.stderr,
        )
        return 3
    print(OwnerAuthService.hash_passcode(secret))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
