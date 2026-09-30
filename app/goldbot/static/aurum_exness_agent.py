#!/usr/bin/env python3
"""
AURUM FP Markets / MetaTrader 5 Windows Agent
========================================
Runs on Windows where MetaTrader 5 terminal is installed and logged into FP Markets.
Connects to the AURUM cloud desk and executes real orders.

Usage:
  pip install MetaTrader5 requests
  python aurum_exness_agent.py --cloud https://pfai-v8.onrender.com --token YOUR_BRIDGE_TOKEN

Keep MT5 open. Use Demo server first (FPMarkets-Demo*).
"""
from __future__ import annotations

import argparse
import sys
import time

try:
    import requests
except ImportError:
    print("Install requests: pip install requests")
    sys.exit(1)


def api(cloud: str, token: str, method: str, path: str, json_body=None):
    url = cloud.rstrip("/") + path
    r = requests.request(
        method,
        url,
        headers={"Authorization": f"Bearer {token}", "User-Agent": "AURUM-FPMarkets-Agent/3.1"},
        json=json_body,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def connect_mt5(creds: dict):
    try:
        import MetaTrader5 as mt5
    except ImportError as e:
        raise RuntimeError("MetaTrader5 package missing. On Windows: pip install MetaTrader5") from e

    kwargs = {}
    if creds.get("path"):
        kwargs["path"] = creds["path"]
    if not mt5.initialize(**kwargs):
        raise RuntimeError(f"mt5.initialize failed: {mt5.last_error()}")
    ok = mt5.login(int(creds["login"]), password=str(creds["password"]), server=str(creds["server"]))
    if not ok:
        err = mt5.last_error()
        mt5.shutdown()
        raise RuntimeError(f"mt5.login failed: {err}")
    return mt5


def account_snap(mt5) -> dict:
    info = mt5.account_info()
    if info is None:
        return {}
    return {
        "balance": float(info.balance),
        "equity": float(info.equity),
        "margin": float(info.margin),
        "free_margin": float(info.margin_free),
        "currency": str(info.currency),
        "server": str(info.server),
        "login": int(info.login),
        "leverage": int(info.leverage),
        "mode": "mt5",
        "connected": True,
    }


def execute_order(mt5, payload: dict) -> dict:
    symbol = payload.get("symbol") or "XAUUSD"
    side = payload.get("side")
    lot = float(payload.get("lot") or 0.01)
    sl = float(payload.get("sl") or 0)
    tp = float(payload.get("tp") or 0)
    comment = str(payload.get("comment") or "AURUM")[:30]

    if mt5.symbol_info(symbol) is None:
        if not mt5.symbol_select(symbol, True):
            return {"ok": False, "error": f"symbol_select failed {mt5.last_error()}"}

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return {"ok": False, "error": f"no tick {mt5.last_error()}"}

    order_type = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL
    price = tick.ask if side == "buy" else tick.bid
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": order_type,
        "price": float(price),
        "sl": float(sl),
        "tp": float(tp),
        "deviation": 40,
        "magic": 908070,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result is None:
        return {"ok": False, "error": str(mt5.last_error())}
    ok = result.retcode == mt5.TRADE_RETCODE_DONE
    return {
        "ok": ok,
        "mode": "mt5",
        "retcode": int(result.retcode),
        "ticket": int(getattr(result, "order", 0) or 0),
        "price": float(getattr(result, "price", price) or price),
        "side": side,
        "lot": lot,
        "sl": sl,
        "tp": tp,
        "comment": comment,
        "error": None if ok else str(result.comment),
    }


def main():
    p = argparse.ArgumentParser(description="AURUM FP Markets MT5 agent")
    p.add_argument("--cloud", required=True, help="AURUM cloud URL")
    p.add_argument("--token", required=True, help="Bridge token from web login")
    p.add_argument("--poll", type=float, default=1.0, help="Poll seconds")
    args = p.parse_args()

    print("Fetching MT5 credentials from AURUM cloud...")
    creds = api(args.cloud, args.token, "GET", "/api/bridge/credentials")
    print(f"Connecting MT5 login={creds['login']} server={creds['server']} symbol={creds.get('symbol')}")
    mt5 = connect_mt5(creds)
    print("MT5 connected:", account_snap(mt5))

    while True:
        try:
            snap = account_snap(mt5)
            api(
                args.cloud,
                args.token,
                "POST",
                "/api/bridge/heartbeat",
                {
                    "info": {"agent": "aurum_exness_agent", "version": "3.1.0", "python": sys.version.split()[0]},
                    "account": snap,
                },
            )
            polled = api(args.cloud, args.token, "GET", "/api/bridge/poll")
            for cmd in polled.get("commands") or []:
                print("Command", cmd.get("id"), cmd.get("kind"))
                if cmd.get("kind") == "order_market":
                    result = execute_order(mt5, cmd.get("payload") or {})
                else:
                    result = {"ok": False, "error": f"unknown_kind:{cmd.get('kind')}"}
                api(
                    args.cloud,
                    args.token,
                    "POST",
                    "/api/bridge/complete",
                    {"command_id": cmd["id"], "result": result},
                )
                print("Result", result)
        except Exception as e:
            print("loop error:", e)
        time.sleep(max(0.5, args.poll))


if __name__ == "__main__":
    main()
