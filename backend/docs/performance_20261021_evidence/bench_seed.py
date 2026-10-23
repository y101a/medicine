"""在隔离库（55432）里直接造一个压测账号，绕开短信验证码。"""

import asyncio

from app.core.security import encrypt_sensitive, hash_password, sensitive_fingerprint
from app.db.session import SessionLocal
from app.models import Gender, User, UserCredentials
from app.services.auth import normalize_username

USERNAME = "bench_load_user"
PASSWORD = "Bench!Load#2026"
PHONE = "13900000001"
ID_CARD = "110101199001010011"


async def main() -> None:
    async with SessionLocal() as db:
        normalized = normalize_username(USERNAME)
        existing = await db.scalar(
            __import__("sqlalchemy").select(User).where(User.username_normalized == normalized)
        )
        if existing is not None:
            print("账号已存在:", existing.id)
            return
        user = User(
            username=USERNAME,
            username_normalized=normalized,
            real_name_ciphertext=encrypt_sensitive("压测账号"),
            phone_ciphertext=encrypt_sensitive(PHONE),
            phone_fingerprint=sensitive_fingerprint(PHONE),
            id_card_ciphertext=encrypt_sensitive(ID_CARD),
            id_card_fingerprint=sensitive_fingerprint(ID_CARD),
            gender=list(Gender)[0],
        )
        user.credentials = UserCredentials(password_hash=hash_password(PASSWORD))
        db.add(user)
        await db.commit()
        print("已创建账号:", user.id, "用户名:", USERNAME)


if __name__ == "__main__":
    asyncio.run(main())