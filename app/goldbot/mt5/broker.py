"""Active broker profile — FP Markets (MT5 / cTrader)."""
from __future__ import annotations

import re

BROKER_NAME = "FP Markets"
BROKER_ID = "fpmarkets"
BROKER_SHORT = "FPMarkets"

# Common MT5 server names (exact string must match the portal / MT5 login email)
DEFAULT_SERVER = "FPMarkets-Live"
DEFAULT_SYMBOL = "XAUUSD"

METAAPI_KEYWORDS = [
    "FP Markets",
    "FPMarkets",
    "First Prudential Markets",
    "FP Markets Ltd",
    "FP Markets LLC",
    "FP Trading",
]


def _fp_servers() -> list[str]:
    out: list[str] = [
        "FPMarkets-Live",
        "FPMarkets-Live2",
        "FPMarkets-Live3",
        "FPMarkets-Live4",
        "FPMarkets-Live5",
        "FPMarkets-Demo",
        "FPMarkets-Demo2",
        "FPTrading-Live",
        "FPTrading-Demo",
    ]
    return out


BROKER_SERVERS = _fp_servers()

# Backward-compatible aliases used by older imports/tests
EXNESS_SERVERS = BROKER_SERVERS  # deprecated name — now FP Markets list


def normalize_broker_server(server: str | None) -> str:
    """Normalize FP Markets (and legacy Exness) MT5 server paste variants."""
    s = str(server or "").strip()
    if not s:
        return ""
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-{2,}", "-", s)

    # FP Markets / FP Trading
    s_fp = re.sub(r"(?i)^fp\s*-?\s*markets?-?", "FPMarkets-", s)
    s_fp = re.sub(r"(?i)^fpmarkets?-?", "FPMarkets-", s_fp)
    s_fp = re.sub(r"(?i)^fp\s*-?\s*trading?-?", "FPTrading-", s_fp)
    s_fp = re.sub(r"(?i)^fptrading?-?", "FPTrading-", s_fp)
    low = s_fp.lower()
    if low.startswith("fpmarkets-"):
        tail = s_fp[len("FPMarkets-") :]
        if tail.startswith("-"):
            tail = tail[1:]
        compact = tail.replace("-", "")
        m = re.match(r"(?i)^(live)(\d*)$", compact)
        if m:
            return "FPMarkets-Live" + (m.group(2) or "")
        m = re.match(r"(?i)^(demo)(\d*)$", compact)
        if m:
            return "FPMarkets-Demo" + (m.group(2) or "")
        return "FPMarkets-" + tail
    if low.startswith("fptrading-"):
        tail = s_fp[len("FPTrading-") :]
        if tail.startswith("-"):
            tail = tail[1:]
        compact = tail.replace("-", "")
        m = re.match(r"(?i)^(live)(\d*)$", compact)
        if m:
            return "FPTrading-Live" + (m.group(2) or "")
        m = re.match(r"(?i)^(demo)(\d*)$", compact)
        if m:
            return "FPTrading-Demo" + (m.group(2) or "")
        return "FPTrading-" + tail

    # Legacy Exness paste (still normalize if present)
    s_ex = re.sub(r"(?i)^exness-?mt5-?", "Exness-MT5", s)
    low = s_ex.lower()
    if low.startswith("exness-mt5"):
        tail = s_ex[len("Exness-MT5") :]
        if tail.startswith("-"):
            tail = tail[1:]
        if tail.lower().startswith("trial"):
            num = re.sub(r"(?i)^trial-?", "", tail)
            return "Exness-MT5Trial" + num
        if tail.lower().startswith("real"):
            num = re.sub(r"(?i)^real-?", "", tail)
            return "Exness-MT5Real" + num
        return "Exness-MT5" + tail

    return s_fp


def servers_compatible(a: str | None, b: str | None) -> bool:
    na = normalize_broker_server(a) or str(a or "").strip()
    nb = normalize_broker_server(b) or str(b or "").strip()
    if not na or not nb:
        return False
    if na.lower() == nb.lower():
        return True
    return na.lower().replace("-", "") == nb.lower().replace("-", "")


def is_broker_server_suggestion(name: str) -> bool:
    """Accept only FP Markets (or FP Trading) server suggestions — never Exness."""
    low = str(name or "").lower().replace(" ", "")
    if "exness" in low:
        return False
    return any(k in low for k in ("fpmarkets", "fptrading", "fpmarketsllc", "firstprudential"))


# Deprecated alias
normalize_exness_server = normalize_broker_server
