import time

from goldbot.brain.fast_pulse import FastPulse
from goldbot.execution.smart_exits import manage_trade
from goldbot.market.candles import Candle


def _cs(n=80, start=4100.0):
    out = []
    px = start
    for i in range(n):
        o = px
        c = px + 0.4
        out.append(Candle(1_700_000_000 + i * 900, o, c + 0.8, o - 0.8, c, 1000))
        px = c
    return out


def test_fast_pulse_detects_impulse():
    fp = FastPulse()
    t0 = time.time()
    px = 4100.0
    for i in range(20):
        px += 0.35
        fp.push(px, px + 0.2, ts=t0 + i * 0.05)
    p = fp.analyze(_cs())
    assert p["bias"] == "buy"
    assert p["score"] > 0
    assert fp.confirms("buy", p)


def test_break_even_lock():
    cs = _cs()
    trade = {
        "id": 1,
        "side": "buy",
        "entry": 4100.0,
        "sl": 4090.0,
        "tp": 4125.0,
        "lot": 0.05,
        "mode": "paper",
        "ts": time.time(),
        "meta": {},
    }
    # +1.2R => mark at 4112
    upd, cls, ev = manage_trade(trade, bid=4112.0, ask=4112.3, candles=cs, pulse={"bias": "buy", "score": 0.2})
    assert cls is None
    assert upd is not None
    assert upd["sl"] >= 4100.0
    assert (upd.get("meta") or {}).get("be_locked") or (ev or {}).get("type") in {"break_even", "partial_tp", "trail"}
