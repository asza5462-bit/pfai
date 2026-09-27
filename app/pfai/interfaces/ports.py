"""Replaceable infrastructure ports — Core must not hard-depend on one vendor.

Concrete adapters (SQLite, local files, Hash embeddings, Echo/Mock models)
exist today; future adapters (Postgres, remote vectors, new LLMs, new hosts)
plug in behind these Protocols without rewriting product logic.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class StoragePort(Protocol):
    """Durable key/document/row storage (today: SQLite / JSON files)."""

    def get(self, key: str) -> Any: ...
    def put(self, key: str, value: Any) -> None: ...
    def delete(self, key: str) -> bool: ...
    def list_keys(self, prefix: str = "") -> list[str]: ...


@runtime_checkable
class RelationalStorePort(Protocol):
    """SQL-ish store port — enables SQLite → Postgres migration later."""

    def execute(self, sql: str, params: tuple | list | None = None) -> Any: ...
    def fetchall(self, sql: str, params: tuple | list | None = None) -> list[Any]: ...
    def commit(self) -> None: ...


@runtime_checkable
class VectorStorePort(Protocol):
    """Vector index port — independent of embedding vendor and DB engine."""

    def add(self, content: str, source: str = "", metadata: dict[str, Any] | None = None) -> Any: ...
    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]: ...


@runtime_checkable
class EmbeddingPort(Protocol):
    """Embedding model port — HashEmbedding today; swap without touching Memory."""

    def embed(self, text: str) -> list[float]: ...


@runtime_checkable
class BlobStorePort(Protocol):
    """Binary/object storage (artifacts, exports, large payloads)."""

    def write(self, name: str, data: bytes) -> str: ...
    def read(self, name: str) -> bytes: ...
    def exists(self, name: str) -> bool: ...


@runtime_checkable
class ExportPort(Protocol):
    """Full portable export so knowledge is never locked to one vendor."""

    def export_bundle(self, target_dir: str, *, include: list[str] | None = None) -> dict[str, Any]: ...
    def import_bundle(self, source_dir: str, *, dry_run: bool = True) -> dict[str, Any]: ...


@runtime_checkable
class ClockPort(Protocol):
    """Time abstraction for deterministic tests and clock changes."""

    def now_iso(self) -> str: ...
