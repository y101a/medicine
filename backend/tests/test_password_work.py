import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from anyio import CancelScope, CapacityLimiter
from fastapi import Response

from app.core import password_work
from app.core.errors import AppError
from app.core.security import hash_password, verify_password
from app.schemas.auth import LoginRequest
from app.services import auth


async def test_real_password_verification_keeps_algorithm_and_results():
    encoded = await password_work.run_password_work(hash_password, "Synthetic!Password")
    assert encoded.startswith("$argon2id$")
    assert await password_work.run_password_work(verify_password, "Synthetic!Password", encoded)
    assert not await password_work.run_password_work(verify_password, "wrong", encoded)


async def test_cpu_work_leaves_event_loop_available_and_has_bounded_parallelism(monkeypatch):
    monkeypatch.setattr(password_work, "_password_limiter", CapacityLimiter(2))
    release = threading.Event()
    started = []
    main_thread = threading.get_ident()

    def blocking():
        started.append(threading.get_ident())
        assert release.wait(5)
        return True

    tasks = [asyncio.create_task(password_work.run_password_work(blocking)) for _ in range(3)]
    try:
        async with asyncio.timeout(3):
            while len(started) < 2:
                await asyncio.sleep(0.005)
        # We can run here while two workers remain blocked; third must wait.
        await asyncio.sleep(0.02)
        assert len(started) == 2
        assert all(item != main_thread for item in started)
    finally:
        release.set()
        assert all(await asyncio.gather(*tasks))
    assert len(started) == 3


async def test_exception_releases_capacity(monkeypatch):
    monkeypatch.setattr(password_work, "_password_limiter", CapacityLimiter(1))

    def fail():
        raise ValueError("synthetic")

    with pytest.raises(ValueError, match="synthetic"):
        await password_work.run_password_work(fail)
    assert await password_work.run_password_work(lambda: 42) == 42


async def test_cancelled_request_holds_capacity_until_thread_finishes(monkeypatch):
    monkeypatch.setattr(password_work, "_password_limiter", CapacityLimiter(1))
    release = threading.Event()
    started = []
    scopes = []

    def blocking():
        started.append(True)
        assert release.wait(5)

    async def cancellable_request():
        with CancelScope() as scope:
            scopes.append(scope)
            await password_work.run_password_work(blocking)

    first = asyncio.create_task(cancellable_request())
    second = None
    try:
        async with asyncio.timeout(3):
            while not started:
                await asyncio.sleep(0.005)
        scopes[0].cancel()
        second = asyncio.create_task(password_work.run_password_work(blocking))
        await asyncio.sleep(0.02)
        assert len(started) == 1
    finally:
        release.set()
        await asyncio.gather(first, *([second] if second else []))
    assert len(started) == 2


async def test_nonexistent_account_dummy_hash_is_offloaded(monkeypatch):
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    called_from = []
    monkeypatch.setattr(auth, "hash_password", lambda _: called_from.append(threading.get_ident()))
    with pytest.raises(AppError) as error:
        await auth.login_user(
            LoginRequest(username="missing", password="synthetic"), None, Response(), db
        )
    assert error.value.status_code == 401
    assert called_from and called_from[0] != threading.get_ident()


async def test_wrong_password_counter_and_lock_are_preserved(monkeypatch):
    credentials = SimpleNamespace(locked_until=None, failed_attempts=4, password_hash="synthetic")
    user = SimpleNamespace(credentials=credentials)
    result = MagicMock()
    result.scalar_one_or_none.return_value = user
    db = SimpleNamespace(execute=AsyncMock(return_value=result), commit=AsyncMock(),
                         refresh=AsyncMock())
    threads = []

    def invalid(*_):
        threads.append(threading.get_ident())
        return False

    monkeypatch.setattr(auth, "verify_password", invalid)
    payload = LoginRequest(username="synthetic", password="wrong")
    with pytest.raises(AppError) as failed:
        await auth.login_user(payload, None, Response(), db)
    assert failed.value.status_code == 401
    assert credentials.failed_attempts == 0
    assert credentials.locked_until is not None
    db.commit.assert_awaited_once()
    with pytest.raises(AppError) as locked:
        await auth.login_user(payload, None, Response(), db)
    assert locked.value.status_code == 423
    assert len(threads) == 1 and threads[0] != threading.get_ident()
