"""Tiny in-memory sliding-window rate limiter (per process; resets on restart).

Behind a reverse proxy the client IP comes from X-Forwarded-For (first hop).
That header is spoofable if the app is exposed directly — fine for a small demo,
use a real gateway/Redis-backed limiter for anything bigger.
"""
import os
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request

from models import User
from services.auth import get_current_user

_hits: dict[tuple, deque] = defaultdict(deque)


def _enabled() -> bool:
    return os.getenv("RATE_LIMIT_ENABLED", "true").lower() not in ("0", "false", "no")


def client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check(key: tuple, max_calls: int, window_s: int):
    now = time.monotonic()
    q = _hits[key]
    while q and now - q[0] > window_s:
        q.popleft()
    if len(q) >= max_calls:
        retry = int(window_s - (now - q[0])) + 1
        raise HTTPException(
            429, f"Too many requests. Try again in {retry}s.", headers={"Retry-After": str(retry)}
        )
    q.append(now)


def ip_limit(name: str, max_calls: int, window_s: int):
    def dep(request: Request):
        if _enabled():
            _check((name, client_ip(request)), max_calls, window_s)
    return dep


def user_limit(name: str, max_calls: int, window_s: int):
    def dep(user: User = Depends(get_current_user)):
        if _enabled():
            _check((name, user.id), max_calls, window_s)
    return dep
