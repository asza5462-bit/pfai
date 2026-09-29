"""Exness gold symbol helpers — brokers often use XAUUSDm / XAUUSDc suffixes."""
from __future__ import annotations

# Common Exness gold symbols across account types
EXNESS_GOLD_SYMBOLS = (
    "XAUUSDm",
    "XAUUSDc",
    "XAUUSDr",
    "XAUUSD",
    "GOLD",
    "XAUUSDs",
)


def normalize_symbol(symbol: str | None) -> str:
    s = (symbol or "XAUUSD").strip().upper()
    if not s:
        return "XAUUSD"
    # Treat bare gold as Exness micro/default candidate list head
    if s in {"XAU", "GOLD", "XAUUSD"}:
        return "XAUUSD"
    return s


def symbol_candidates(symbol: str | None = None) -> list[str]:
    """Ordered candidates to try when placing/quoting on Exness."""
    primary = normalize_symbol(symbol)
    out: list[str] = []
    for s in (primary, *EXNESS_GOLD_SYMBOLS):
        if s not in out:
            out.append(s)
    return out
