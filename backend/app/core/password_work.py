"""Bound password CPU work without occupying the request event-loop thread."""

from collections.abc import Callable

from anyio import CapacityLimiter, to_thread

# Argon2 also consumes substantial memory. This is a per-worker limit, shared
# by the real-password and nonexistent-account paths, not a request rate limit.
PASSWORD_WORK_CONCURRENCY = 2
_password_limiter = CapacityLimiter(PASSWORD_WORK_CONCURRENCY)


async def run_password_work[T](function: Callable[..., T], *args: object) -> T:
    # Keep the capacity token until work finishes, including cancelled requests.
    return await to_thread.run_sync(
        function, *args, limiter=_password_limiter, abandon_on_cancel=False
    )
