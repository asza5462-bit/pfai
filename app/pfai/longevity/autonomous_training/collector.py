"""Collect eligible experiences from approved PFAI sources (no raw secrets)."""
from __future__ import annotations

import time
from typing import Any, Callable, Iterable


CollectorFn = Callable[[], Iterable[dict[str, Any]]]


class ExperienceCollector:
    """Gathers candidate training rows from pluggable source callbacks."""

    def __init__(self) -> None:
        self._sources: dict[str, CollectorFn] = {}

    def register(self, name: str, fn: CollectorFn) -> None:
        self._sources[name] = fn

    def collect(self, *, sources: list[str] | None = None) -> list[dict[str, Any]]:
        names = sources or list(self._sources.keys())
        rows: list[dict[str, Any]] = []
        now = time.time()
        for name in names:
            fn = self._sources.get(name)
            if not fn:
                continue
            try:
                batch = list(fn() or [])
            except Exception:
                continue
            for item in batch:
                row = dict(item)
                row.setdefault("source", name)
                row.setdefault("source_id", str(row.get("id") or row.get("candidate_id") or ""))
                row.setdefault("timestamp", now)
                # Normalize instruction/response fields
                if "instruction" not in row and "content" in row:
                    content = str(row.get("content") or "")
                    row["instruction"] = f"Recall verified knowledge from {name}"
                    row["response"] = content
                rows.append(row)
        return rows


def collect_from_learning_pipeline(pipeline: Any, *, statuses: tuple[str, ...] = ("stored", "validated")) -> list[dict[str, Any]]:
    """Pull validated/stored durable learning candidates when API exists."""
    out: list[dict[str, Any]] = []
    if pipeline is None:
        return out
    # Prefer explicit list API if present; otherwise scan sqlite via getattr
    lister = getattr(pipeline, "list_candidates", None)
    if callable(lister):
        for status in statuses:
            try:
                for cand in lister(status=status, limit=500) or []:
                    content = getattr(cand, "content", None) or (cand.get("content") if isinstance(cand, dict) else "")
                    if not content:
                        continue
                    out.append(
                        {
                            "instruction": "Apply this verified PFAI lesson",
                            "response": str(content),
                            "source": "durable_learning",
                            "source_id": getattr(cand, "candidate_id", "") or (cand.get("candidate_id") if isinstance(cand, dict) else ""),
                            "verified": True,
                            "provenance": {"pipeline_status": status},
                        }
                    )
            except Exception:
                continue
        return out
    # Fallback via raw db if available
    db = getattr(pipeline, "db", None)
    if db is None:
        return out
    try:
        placeholders = ",".join("?" * len(statuses))
        cur = db.execute(
            f"SELECT candidate_id, content, status, confidence FROM learning_candidates WHERE status IN ({placeholders}) LIMIT 500",
            statuses,
        )
        for row in cur.fetchall():
            out.append(
                {
                    "instruction": "Apply this verified PFAI lesson",
                    "response": str(row[1] or ""),
                    "source": "durable_learning",
                    "source_id": str(row[0]),
                    "verified": True,
                    "provenance": {"pipeline_status": row[2], "confidence": row[3]},
                }
            )
    except Exception:
        return out
    return out
