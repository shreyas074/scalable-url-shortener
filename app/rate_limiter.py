"""
Simple per-IP token bucket rate limiter, implemented as ASGI middleware.

Why token bucket: it allows short bursts (good UX) while still enforcing a
steady average rate, unlike a fixed-window counter which lets clients double
their allowed rate right at window boundaries. This is a common interview
talking point when discussing API rate limiting design.
"""
import time
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class TokenBucket:
    def __init__(self, capacity: int, refill_rate_per_sec: float):
        self.capacity = capacity
        self.refill_rate = refill_rate_per_sec
        self.tokens = capacity
        self.last_refill = time.monotonic()
        self.lock = Lock()

    def allow(self) -> bool:
        with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_refill = now
            if self.tokens >= 1:
                self.tokens -= 1
                return True
            return False


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    capacity: burst size (max requests in an instant)
    refill_rate_per_sec: sustained requests/sec allowed thereafter
    """

    def __init__(self, app, capacity: int = 20, refill_rate_per_sec: float = 5.0):
        super().__init__(app)
        self.capacity = capacity
        self.refill_rate = refill_rate_per_sec
        self.buckets: dict[str, TokenBucket] = {}
        self.buckets_lock = Lock()

    def _get_bucket(self, client_ip: str) -> TokenBucket:
        with self.buckets_lock:
            if client_ip not in self.buckets:
                self.buckets[client_ip] = TokenBucket(self.capacity, self.refill_rate)
            return self.buckets[client_ip]

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        bucket = self._get_bucket(client_ip)

        if not bucket.allow():
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Slow down."},
            )

        return await call_next(request)
