"""CLI helper: hash an owner passcode from stdin for env configuration.

Never commit the output into Git. Paste the hash into platform secrets only.

Usage:
  python -m pfai.hash_owner_secret
  # type passcode, Enter, Ctrl-D
"""
from __future__ import annotations

import getpass
import sys

from pfai.owner_auth import OwnerAuthService


def main() -> int:
    try:
        secret = getpass.getpass("Owner passcode (input hidden): ")
    except Exception:
        secret = sys.stdin.readline().rstrip("\n")
    if not secret:
        print("empty passcode", file=sys.stderr)
        return 2
    if not OwnerAuthService.passcode_strong(secret):
        print(
            "weak passcode: use >=12 chars with mixed upper/lower/digit/symbol",
            file=sys.stderr,
        )
        return 3
    print(OwnerAuthService.hash_passcode(secret))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
