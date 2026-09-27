"""Backup, Restore, and Disaster Recovery contracts.

Builds on existing BackupManager + DisasterRecovery without replacing them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class BackupRecord:
    backup_id: str
    created_at: str
    label: str = ""
    checksum: str = ""
    path: str = ""
    verified: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class RestoreReport:
    ok: bool
    backup_id: str = ""
    message: str = ""
    rolled_back_from: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class BackupPort(Protocol):
    def create(self, label: str | None = None) -> BackupRecord:
        ...

    def list_backups(self) -> list[BackupRecord]:
        ...

    def verify(self, backup_id: str) -> bool:
        ...


@runtime_checkable
class RestorePort(Protocol):
    def restore(self, backup_id: str, *, approved: bool = False) -> RestoreReport:
        ...


@runtime_checkable
class DisasterRecoveryPort(Protocol):
    def integrity(self) -> dict[str, Any]:
        ...

    def snapshot(self, label: str = "auto") -> str:
        ...

    def recover(self, *, approved: bool = False) -> dict[str, Any]:
        ...
