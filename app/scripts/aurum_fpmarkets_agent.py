#!/usr/bin/env python3
"""
AURUM FP Markets / MetaTrader 5 Windows Agent
========================================
Runs on Windows where MetaTrader 5 terminal is installed and logged into FP Markets.
Connects to the AURUM cloud desk and executes real orders.

Usage:
  pip install MetaTrader5 requests
  python aurum_fpmarkets_agent.py --cloud https://pfai-v8.onrender.com --token YOUR_BRIDGE_TOKEN

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
        headers={"Authorization": f"Bearer {token}", "User-Agent": "AURUM-FPMarkets-Agent/3.8"},
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


def close_position(mt5, payload: dict) -> dict:
    pid = payload.get("position_id") or payload.get("ticket")
    if pid in (None, "", 0, "0"):
        return {"ok": False, "error": "no_position_id", "mode": "mt5", "execution": "windows_bridge"}
    try:
        position_id = int(pid)
    except (TypeError, ValueError):
        return {"ok": False, "error": "bad_position_id", "mode": "mt5", "execution": "windows_bridge"}
    positions = mt5.positions_get(ticket=position_id) or mt5.positions_get()
    target = None
    for pos in positions or []:
        if int(getattr(pos, "ticket", 0) or 0) == position_id or int(getattr(pos, "identifier", 0) or 0) == position_id:
            target = pos
            break
    if target is None:
        return {"ok": True, "already_closed": True, "mode": "mt5", "execution": "windows_bridge"}
    symbol = str(getattr(target, "symbol", "") or payload.get("symbol") or "XAUUSD")
    volume = float(payload.get("volume") or getattr(target, "volume", 0) or 0)
    if volume <= 0:
        return {"ok": False, "error": "bad_volume", "mode": "mt5", "execution": "windows_bridge"}
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return {"ok": False, "error": f"no tick {mt5.last_error()}", "mode": "mt5", "execution": "windows_bridge"}
    # POSITION_TYPE_BUY = 0 → close with SELL
    is_buy = int(getattr(target, "type", 0) or 0) == 0
    order_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
    price = tick.bid if is_buy else tick.ask
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "position": int(getattr(target, "ticket", position_id) or position_id),
        "price": float(price),
        "deviation": 40,
        "magic": 908070,
        "comment": "AURUM-CLOSE",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result is None:
        return {"ok": False, "error": str(mt5.last_error()), "mode": "mt5", "execution": "windows_bridge"}
    ok = result.retcode == mt5.TRADE_RETCODE_DONE
    return {
        "ok": ok,
        "mode": "mt5",
        "execution": "windows_bridge",
        "retcode": int(result.retcode),
        "ticket": int(getattr(result, "order", 0) or 0),
        "price": float(getattr(result, "price", price) or price),
        "error": None if ok else str(result.comment),
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
                    "info": {"agent": "aurum_fpmarkets_agent", "version": "3.8.2", "python": sys.version.split()[0]},
                    "account": snap,
                },
            )
            polled = api(args.cloud, args.token, "GET", "/api/bridge/poll")
            for cmd in polled.get("commands") or []:
                print("Command", cmd.get("id"), cmd.get("kind"))
                if cmd.get("kind") == "order_market":
                    result = execute_order(mt5, cmd.get("payload") or {})
                elif cmd.get("kind") == "close_position":
                    result = close_position(mt5, cmd.get("payload") or {})
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
