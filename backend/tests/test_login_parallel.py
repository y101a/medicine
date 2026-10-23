import asyncio
from uuid import uuid4

import httpx
from sqlalchemy import delete, select

from app.core.password_work import run_password_work
from app.core.security import encrypt_sensitive, hash_password
from app.db.session import SessionLocal, engine
from app.main import app
from app.models import Gender, User, UserCredentials


async def test_parallel_wrong_passwords_reach_lock_without_lost_updates():
    suffix = uuid4().hex
    username = f"parallel{suffix[:10]}"
    encoded = await run_password_work(hash_password, "Synthetic!Correct")
    async with SessionLocal() as db:
        user = User(
            username=username, username_normalized=username,
            real_name_ciphertext=encrypt_sensitive("合成测试"),
            phone_ciphertext=encrypt_sensitive("13900000000"), phone_fingerprint=suffix,
            id_card_ciphertext=encrypt_sensitive("11010519491231002X"),
            id_card_fingerprint=suffix, gender=Gender.PRIVATE,
        )
        user.credentials = UserCredentials(password_hash=encoded)
        db.add(user)
        await db.commit()
        user_id = user.id
    try:
        async with httpx.AsyncClient(
            base_url="http://test", transport=httpx.ASGITransport(app=app)
        ) as client:
            responses = await asyncio.gather(*[
                client.post("/api/v1/auth/login", json={
                    "username": username, "password": "Synthetic!Wrong"})
                for _ in range(10)
            ])
            statuses = [r.status_code for r in responses]
            assert statuses.count(401) == 5
            assert statuses.count(423) == 5
            locked = await client.post("/api/v1/auth/login", json={
                "username": username, "password": "Synthetic!Correct"})
            assert locked.status_code == 423
        async with SessionLocal() as db:
            credentials = await db.scalar(select(UserCredentials).where(
                UserCredentials.user_id == user_id))
            assert credentials.locked_until is not None
            assert credentials.failed_attempts == 0
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()
        await engine.dispose()
