"""FP Markets gold symbol helpers — primary XAUUSD; keep micro suffixes if present."""
from __future__ import annotations

from goldbot.mt5.broker import DEFAULT_SYMBOL

# Common gold symbols across account types (FP Markets uses XAUUSD)
GOLD_SYMBOLS = (
    "XAUUSD",
    "XAUUSDm",
    "XAUUSDc",
    "XAUUSDr",
    "GOLD",
    "XAUUSDs",
)



def normalize_symbol(symbol: str | None) -> str:
    """Normalize gold symbol; FP Markets default is XAUUSD."""
    raw = (symbol or DEFAULT_SYMBOL).strip()
    if not raw:
        return DEFAULT_SYMBOL
    # Map XAUUSDM / xauusdm → XAUUSDm (case-sensitive suffix brokers)
    if len(raw) >= 2 and raw[-1].isalpha() and raw[:-1].upper() == "XAUUSD":
        suf = raw[-1].lower()
        if suf in {"m", "c", "r", "s"}:
            return "XAUUSD" + suf
        return "XAUUSD" + raw[-1]
    s = raw.upper()
    if s in {"XAU", "GOLD", "XAUUSD"}:
        return DEFAULT_SYMBOL
    for known in GOLD_SYMBOLS:
        if s == known.upper():
            return known
    return raw


def symbol_candidates(symbol: str | None = None) -> list[str]:
    """Ordered candidates to try when placing/quoting."""
    primary = normalize_symbol(symbol)
    out: list[str] = []
    for s in (primary, *GOLD_SYMBOLS):
        if s not in out:
            out.append(s)
    return out
