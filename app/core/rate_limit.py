"""Small in-process sliding-window rate limiter.

Limits are per instance: with N Cloud Run instances a client gets at most N times the budget,
which is still enough to stop scripted booking or password guessing.
"""

import threading
import time
from collections import deque

from fastapi import Request

from app.core.config import get_settings


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, *, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            if len(self._hits) > 10_000:
                self._prune(cutoff)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def _prune(self, cutoff: float) -> None:
        for key in [key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff]:
            del self._hits[key]


rate_limiter = RateLimiter()


def client_ip(request: Request) -> str:
    if get_settings().trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        # The load balancer appends the address it saw; earlier entries can be forged by the client.
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        if hops:
            return hops[-1]
    return request.client.host if request.client else "unknown"
