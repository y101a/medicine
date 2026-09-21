from collections import deque
from math import ceil
from threading import Lock
from time import monotonic
from uuid import UUID

from app.core.errors import AppError

UPLOAD_WINDOW_SECONDS = 600
UPLOAD_LIMIT = 10
RESOURCE_UPLOAD_LIMITS = {"voice_audio": 6}

_upload_lock = Lock()
_upload_calls: dict[tuple[str, str], deque[float]] = {}


def _discard_expired(now: float) -> None:
    for key, calls in list(_upload_calls.items()):
        while calls and now - calls[0] >= UPLOAD_WINDOW_SECONDS:
            calls.popleft()
        if not calls:
            _upload_calls.pop(key, None)


def enforce_upload_rate_limit(user_id: UUID, resource_type: str) -> None:
    now = monotonic()
    key = (str(user_id), resource_type)
    with _upload_lock:
        _discard_expired(now)
        calls = _upload_calls.setdefault(key, deque())
        limit = RESOURCE_UPLOAD_LIMITS.get(resource_type, UPLOAD_LIMIT)
        if len(calls) >= limit:
            retry_after = max(1, ceil(UPLOAD_WINDOW_SECONDS - (now - calls[0])))
            raise AppError(
                429,
                "UPLOAD_RATE_LIMITED",
                "上传过于频繁，请稍后再试",
                {"retryAfterSeconds": retry_after},
            )
        calls.append(now)


def _reset_upload_limits() -> None:
    """Clear process-local buckets for deterministic tests."""
    with _upload_lock:
        _upload_calls.clear()
