"""Runtime configuration for AURUM gold desk."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_bool(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    host: str = field(default_factory=lambda: os.getenv("AURUM_HOST", os.getenv("PFAI_HOST", "0.0.0.0")))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", os.getenv("AURUM_PORT", "8000"))))
    data_dir: Path = field(
        default_factory=lambda: Path(os.getenv("AURUM_DATA_DIR", "data/goldbot")).resolve()
    )

    # Trading
    symbol: str = field(default_factory=lambda: os.getenv("AURUM_SYMBOL", "XAUUSDm"))
    timeframe: str = field(default_factory=lambda: os.getenv("AURUM_TIMEFRAME", "M15"))
    mode: str = field(default_factory=lambda: os.getenv("AURUM_MODE", "paper"))  # paper | mt5

    # MT5 / Exness — never commit secrets; set via Render/VPS env
    mt5_login: int = field(default_factory=lambda: _env_int("MT5_LOGIN", 0))
    mt5_password: str = field(default_factory=lambda: os.getenv("MT5_PASSWORD", ""))
    mt5_server: str = field(default_factory=lambda: os.getenv("MT5_SERVER", "Exness-MT5Real"))
    mt5_path: str = field(default_factory=lambda: os.getenv("MT5_PATH", ""))

    # MetaApi cloud — real Exness execution from Linux/Render (no Windows)
    metaapi_token: str = field(default_factory=lambda: os.getenv("METAAPI_TOKEN", os.getenv("META_API_TOKEN", "")))
    metaapi_region: str = field(default_factory=lambda: os.getenv("METAAPI_REGION", "new-york"))
    metaapi_magic: int = field(default_factory=lambda: _env_int("METAAPI_MAGIC", 908070))
    metaapi_connect_timeout: int = field(default_factory=lambda: _env_int("METAAPI_CONNECT_TIMEOUT", 120))
    # Prefer cloud MetaApi over legacy Windows bridge when token is present
    prefer_metaapi: bool = field(default_factory=lambda: _env_bool("AURUM_PREFER_METAAPI", True))

    # Linux Docker/Wine MT5 executor (headless-mt5 compatible) — no Windows OS
    mt5_linux_url: str = field(default_factory=lambda: os.getenv("AURUM_MT5_LINUX_URL", "").rstrip("/"))
    mt5_linux_token: str = field(default_factory=lambda: os.getenv("AURUM_MT5_LINUX_TOKEN", ""))
    # Off by default — MetaApi is the primary no-Windows path; enable only with a Linux executor URL
    prefer_mt5_linux: bool = field(default_factory=lambda: _env_bool("AURUM_PREFER_MT5_LINUX", False))

    # Risk — elite desk defaults (capital preservation first)
    risk_per_trade_pct: float = field(default_factory=lambda: _env_float("AURUM_RISK_PCT", 0.35))
    max_daily_loss_pct: float = field(default_factory=lambda: _env_float("AURUM_MAX_DAILY_LOSS_PCT", 1.25))
    max_open_trades: int = field(default_factory=lambda: _env_int("AURUM_MAX_OPEN", 1))
    min_reward_risk: float = field(default_factory=lambda: _env_float("AURUM_MIN_RR", 2.2))
    max_spread_points: float = field(default_factory=lambda: _env_float("AURUM_MAX_SPREAD", 35.0))
    min_confluence: float = field(default_factory=lambda: _env_float("AURUM_MIN_CONFLUENCE", 0.62))
    cooldown_seconds: int = field(default_factory=lambda: _env_int("AURUM_COOLDOWN_SEC", 120))
    auto_trade: bool = field(default_factory=lambda: _env_bool("AURUM_AUTO_TRADE", False))  # arm only after login/start
    # Dual-loop cadence: fast pulse/manage + slower strategy scan
    loop_seconds: float = field(default_factory=lambda: _env_float("AURUM_LOOP_SECONDS", 6.0))
    tick_seconds: float = field(default_factory=lambda: _env_float("AURUM_TICK_SECONDS", 0.5))
    require_pulse_confirm: bool = field(default_factory=lambda: _env_bool("AURUM_PULSE_CONFIRM", True))
    max_hold_seconds: int = field(default_factory=lambda: _env_int("AURUM_MAX_HOLD_SEC", 10800))
    max_chase_r: float = field(default_factory=lambda: _env_float("AURUM_MAX_CHASE_R", 0.35))

    # Paper account
    paper_balance: float = field(default_factory=lambda: _env_float("AURUM_PAPER_BALANCE", 10_000.0))

    owner_token: str = field(default_factory=lambda: os.getenv("AURUM_OWNER_TOKEN", os.getenv("PFAI_OWNER_TOKEN", "")))

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "logs").mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
