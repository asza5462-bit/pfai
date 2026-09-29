"""FX session map for gold — London / New York killzones."""
from __future__ import annotations

from datetime import datetime, timezone


# UTC hour windows (inclusive start, exclusive end)
SESSIONS = {
    "asia": (0, 7),
    "london": (7, 12),
    "ny_overlap": (12, 16),
    "ny": (13, 21),
    "dead": (21, 24),
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def active_sessions(now: datetime | None = None) -> list[str]:
    now = now or utc_now()
    h = now.hour
    active = []
    for name, (a, b) in SESSIONS.items():
        if a <= h < b:
            active.append(name)
    return active or ["dead"]


def killzone_score(now: datetime | None = None) -> dict:
    """Higher score in London open + NY overlap — historically richest XAU liquidity."""
    now = now or utc_now()
    h = now.hour + now.minute / 60.0
    sessions = active_sessions(now)
    score = 0.25
    label = "off_hours"
    # London open 07:00–10:00 UTC
    if 7.0 <= h < 10.0:
        score = 0.95
        label = "london_open_killzone"
    elif 12.0 <= h < 15.0:
        score = 0.92
        label = "ny_overlap_killzone"
    elif 10.0 <= h < 12.0:
        score = 0.7
        label = "london_mid"
    elif 15.0 <= h < 18.0:
        score = 0.65
        label = "ny_continuation"
    elif "asia" in sessions:
        score = 0.4
        label = "asia_range"
    return {
        "sessions": sessions,
        "killzone": label,
        "session_edge": round(score, 3),
        "utc": now.isoformat(),
        "prefer_trade": score >= 0.65,
    }
