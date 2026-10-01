"""Runtime configuration for NOVA Code."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(slots=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("NOVA_DATA_DIR", "data")).resolve())
    app_secret: str = field(default_factory=lambda: os.getenv("NOVA_APP_SECRET", ""))
    setup_token: str = field(default_factory=lambda: os.getenv("NOVA_SETUP_TOKEN", ""))
    cookie_secure: bool = field(default_factory=lambda: _bool("NOVA_COOKIE_SECURE", True))
    session_days: int = field(default_factory=lambda: _int("NOVA_SESSION_DAYS", 14))
    max_file_bytes: int = field(default_factory=lambda: _int("NOVA_MAX_FILE_BYTES", 1_000_000))
    max_project_bytes: int = field(default_factory=lambda: _int("NOVA_MAX_PROJECT_BYTES", 50_000_000))
    command_timeout: int = field(default_factory=lambda: _int("NOVA_COMMAND_TIMEOUT", 45))
    allow_commands: bool = field(default_factory=lambda: _bool("NOVA_ALLOW_COMMANDS", True))
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    openai_base_url: str = field(
        default_factory=lambda: os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    )
    default_provider: str = field(default_factory=lambda: os.getenv("NOVA_AI_PROVIDER", "openai"))
    default_model: str = field(default_factory=lambda: os.getenv("NOVA_AI_MODEL", "gpt-5.2"))

    @property
    def database_path(self) -> Path:
        return self.data_dir / "nova.sqlite3"

    @property
    def workspace_root(self) -> Path:
        return self.data_dir / "workspaces"

    @property
    def production_ready(self) -> bool:
        return len(self.app_secret) >= 32 and len(self.setup_token) >= 16

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_root.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
