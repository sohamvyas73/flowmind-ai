"""Small in-memory sliding-window rate limiter (per process).

Good enough to blunt brute-force and trigger spam on a single instance; put a shared
limiter (Redis / API gateway) in front when running multiple workers.
"""
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from fastapi import HTTPException, Request, status

from app.core.config import settings


class RateLimiter:
    def __init__(self) -> None:
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window_s: int = 60) -> None:
        if limit <= 0:
            return
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > window_s:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please slow down and try again shortly.",
                headers={"Retry-After": str(window_s)},
            )
        q.append(now)

    def reset(self) -> None:
        self._hits.clear()


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def limit_auth(request: Request) -> None:
    limiter.check(f"auth:{client_ip(request)}", settings.AUTH_RATE_LIMIT_PER_MIN)
