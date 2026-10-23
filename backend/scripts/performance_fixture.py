"""Prepare an isolated local benchmark and serve the unchanged business routes.

Uses only medical_assistant_perf at loopback:55433. Credentials below are public
test-only values and must never be used for an application deployment.
"""

import argparse
import asyncio
import base64
import hashlib
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def configure():
    os.environ.update({
        "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "55433",
        "POSTGRES_USER": "perf", "POSTGRES_PASSWORD": "perf-local-only",
        "POSTGRES_DB": "medical_assistant_perf",
        "APP_ENVIRONMENT": "development", "MCP_ENABLED": "false",
        "NEWS_PORTAL_ENABLED": "false", "WEB_SEARCH_ENABLED": "false",
        "MULTI_AGENT_ENABLED": "false", "SMS_PROVIDER": "fake",
        "JWT_SECRET_KEY": "performance-fixture-only-never-use-in-production",
        "FINGERPRINT_SECRET": "performance-fixture-only-never-use-in-production",
        "FIELD_ENCRYPTION_KEY": base64.urlsafe_b64encode(
            hashlib.sha256(b"public-performance-fixture-only").digest()
        ).decode(),
        "ACCESS_TOKEN_EXPIRE_MINUTES": "180",
        "QWEN_API_KEY": "", "DEEPSEEK_API_KEY": "", "KIMI_API_KEY": "",
        "ZHIPUAI_API_KEY": "", "AI_API_KEY": "",
    })


async def seed(output: Path, user_count: int):
    from sqlalchemy import func, select

    from app.core.config import get_settings
    from app.core.security import create_access_token, encrypt_sensitive
    from app.db.session import SessionLocal, engine
    from app.models import Consultation, Gender, KnowledgeChunk, KnowledgeDocument, Message, User
    from app.rag.prototype_seed import seed_prototype_knowledge
    from app.services.auth import ACCESS_COOKIE

    settings = get_settings()
    if (settings.postgres_db, settings.postgres_port, settings.postgres_host) != (
        "medical_assistant_perf", 55433, "127.0.0.1"
    ):
        raise RuntimeError("Dedicated performance database required")
    try:
        # Reserve path first: refuse to overwrite an existing fixture.
        with output.open("x", encoding="utf-8") as handle:
            async with SessionLocal() as db:
                if await db.scalar(select(func.count()).select_from(User)):
                    raise RuntimeError("Performance database must have no existing users")
                await seed_prototype_knowledge(db)
                users = []
                for _ in range(user_count):
                    suffix = uuid4().hex
                    user = User(
                        username=f"perf{suffix[:12]}", username_normalized=f"perf{suffix[:12]}",
                        real_name_ciphertext=encrypt_sensitive("合成测试用户"),
                        phone_ciphertext=encrypt_sensitive("合成手机号"),
                        phone_fingerprint=suffix,
                        id_card_ciphertext=encrypt_sensitive("合成证件号"),
                        id_card_fingerprint=suffix, gender=Gender.PRIVATE,
                    )
                    db.add(user)
                    await db.flush()
                    first_cid = None
                    for index in range(10):
                        consultation = Consultation(
                            user_id=user.id, client_request_id=uuid4(), message_count=10,
                            title_ciphertext=encrypt_sensitive(f"合成咨询 {index}"),
                        )
                        db.add(consultation)
                        await db.flush()
                        first_cid = first_cid or consultation.id
                        db.add_all([
                            Message(consultation_id=consultation.id, client_request_id=uuid4(),
                                    sequence=n, role="user" if n % 2 else "assistant",
                                    content_ciphertext=encrypt_sensitive(
                                        "合成历史消息，仅用于本地接口性能验证。" * 8
                                    ))
                            for n in range(1, 11)
                        ])
                    write_consultation = Consultation(
                        user_id=user.id, client_request_id=uuid4(), message_count=0,
                        title_ciphertext=encrypt_sensitive("合成写入压测"),
                    )
                    db.add(write_consultation)
                    await db.flush()
                    users.append({
                        "cookie": f"{ACCESS_COOKIE}={create_access_token(user.id)}",
                        "consultation_id": str(first_cid),
                        "write_consultation_id": str(write_consultation.id),
                    })
                await db.flush()
                counts = {"users": user_count, "consultations": user_count * 11,
                          "messages": user_count * 100,
                          "knowledge_documents": await db.scalar(
                              select(func.count()).select_from(KnowledgeDocument)),
                          "knowledge_chunks": await db.scalar(
                              select(func.count()).select_from(KnowledgeChunk)),
                          "vectorized_chunks": 0}
                json.dump({"database": settings.postgres_db, "counts": counts, "users": users},
                          handle, ensure_ascii=False, indent=2)
                handle.flush()
                await db.commit()
                print(json.dumps(counts), flush=True)
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["migrate", "seed", "serve"])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--users", type=int, default=64)
    args = parser.parse_args()
    if args.users < 1 or args.users > 128:
        parser.error("users must be 1..128")
    configure()
    if args.action == "migrate":
        from alembic import command
        from alembic.config import Config

        config = Config(str(BACKEND / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND / "migrations"))
        command.upgrade(config, "head")
    elif args.action == "seed":
        if args.output is None:
            parser.error("--output required for seed")
        asyncio.run(seed(args.output, args.users))
    else:
        import uvicorn

        from app.main import app
        from app.services import health_records
        from app.services.news import auto

        health_records.EXTRACTION_SCHEDULING_ENABLED = False
        auto.AUTO_REFRESH_ENABLED = False
        uvicorn.run(app, host="127.0.0.1", port=58000, workers=1, access_log=False)


if __name__ == "__main__":
    main()
