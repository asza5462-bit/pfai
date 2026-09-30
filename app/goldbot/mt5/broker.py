"""Active broker profile — FP Markets only (MT5 / cTrader)."""
from __future__ import annotations

import re

BROKER_NAME = "FP Markets"
BROKER_ID = "fpmarkets"
BROKER_SHORT = "FPMarkets"

# Exact server strings must match FP Markets portal / MT5 login email
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
    # Extra live/demo shards commonly seen in MT5 server search
    out.extend(f"FPMarkets-Live{i}" for i in range(6, 16))
    out.extend(f"FPMarkets-Demo{i}" for i in range(3, 8))
    return out


BROKER_SERVERS = _fp_servers()


def normalize_broker_server(server: str | None) -> str:
    """Normalize FP Markets / FP Trading MT5 server paste variants."""
    s = str(server or "").strip()
    if not s:
        return ""
    # Reject non-FP brokers explicitly
    if re.search(r"(?i)exness", s):
        return ""
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-{2,}", "-", s)

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
    return s_fp


def is_fp_markets_server(server: str | None) -> bool:
    n = normalize_broker_server(server) if server else ""
    # If raw still looks like FP but normalize emptied (shouldn't), check raw
    if not n:
        return False
    low = n.lower().replace(" ", "")
    return low.startswith("fpmarkets-") or low.startswith("fptrading-")


def resolve_fp_server(server: str | None) -> str:
    """Return normalized FP Markets server or empty string (never another broker)."""
    n = normalize_broker_server(server)
    return n if is_fp_markets_server(n) else ""


def servers_compatible(a: str | None, b: str | None) -> bool:
    na = normalize_broker_server(a) or str(a or "").strip()
    nb = normalize_broker_server(b) or str(b or "").strip()
    if not na or not nb:
        return False
    if na.lower() == nb.lower():
        return True
    return na.lower().replace("-", "") == nb.lower().replace("-", "")


def is_broker_server_suggestion(name: str) -> bool:
    """Accept only FP Markets / FP Trading MetaApi server suggestions."""
    low = str(name or "").lower().replace(" ", "")
    if "exness" in low:
        return False
    return any(k in low for k in ("fpmarkets", "fptrading", "fpmarketsllc", "firstprudential"))
