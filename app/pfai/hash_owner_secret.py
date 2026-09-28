"""CLI helper: hash an owner password from a hidden prompt for env configuration.

Never commit the output into Git. Paste the hash into platform secrets only
as PFAI_OWNER_PASSWORD_HASH. Never paste the plaintext password into chat.

Usage:
  cd app && python -m pfai.hash_owner_secret
  # type password at the hidden prompt, Enter
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
    digest = OwnerAuthService.hash_passcode(secret)
    # Print hash only — never echo the plaintext password.
    print(digest)
    print(
        "Set Render secret PFAI_OWNER_PASSWORD_HASH to the line above. "
        "Do not commit or paste the password into chat.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
