"""Lightweight in-memory rate limiter for auth / provision endpoints."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, *, limit: int, window_sec: float) -> tuple[bool, float]:
        """Return (allowed, retry_after_seconds)."""
        now = time.time()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_sec:
                q.popleft()
            if len(q) >= limit:
                retry = max(0.0, window_sec - (now - q[0]))
                return False, retry
            q.append(now)
            return True, 0.0


limiter = RateLimiter()
