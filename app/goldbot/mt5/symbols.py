"""Exness gold symbol helpers — brokers often use XAUUSDm / XAUUSDc suffixes."""
from __future__ import annotations

# Common Exness gold symbols across account types (preserve suffix case)
EXNESS_GOLD_SYMBOLS = (
    "XAUUSDm",
    "XAUUSDc",
    "XAUUSDr",
    "XAUUSD",
    "GOLD",
    "XAUUSDs",
)


def normalize_symbol(symbol: str | None) -> str:
    """Normalize gold symbol without destroying Exness micro suffix (m/c/r)."""
    raw = (symbol or "XAUUSDm").strip()
    if not raw:
        return "XAUUSDm"
    # Map XAUUSDM / xauusdm → XAUUSDm (Exness is case-sensitive on suffix)
    if len(raw) >= 2 and raw[-1].isalpha() and raw[:-1].upper() == "XAUUSD":
        suf = raw[-1].lower()
        if suf in {"m", "c", "r", "s"}:
            return "XAUUSD" + suf
        return "XAUUSD" + raw[-1]
    s = raw.upper()
    if s in {"XAU", "GOLD", "XAUUSD"}:
        return "XAUUSDm"  # Exness retail default
    # Known full symbols with mixed case
    for known in EXNESS_GOLD_SYMBOLS:
        if s == known.upper():
            return known
    return raw


def symbol_candidates(symbol: str | None = None) -> list[str]:
    """Ordered candidates to try when placing/quoting on Exness."""
    primary = normalize_symbol(symbol)
    out: list[str] = []
    for s in (primary, *EXNESS_GOLD_SYMBOLS):
        if s not in out:
            out.append(s)
    return out
