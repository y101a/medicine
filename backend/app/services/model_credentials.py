from collections import defaultdict, deque
from datetime import UTC, datetime
from threading import Lock
from time import monotonic
from uuid import UUID

import httpx
from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.provider import chat_completions_url
from app.ai.registry import (
    MODEL_DEFINITIONS,
    ModelConfig,
    get_model_definition,
    get_provider_definition,
    model_config,
)
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import decrypt_sensitive, encrypt_sensitive
from app.models import UserModelCredential
from app.schemas.model_credentials import ModelCredentialOut

VERIFY_WINDOW_SECONDS = 600
VERIFY_LIMIT = 5
VERIFY_TIMEOUT_SECONDS = 8
_verification_lock = Lock()
_verification_calls: dict[str, deque[float]] = defaultdict(deque)


def mask_api_key(api_key: str) -> str:
    if len(api_key) <= 8:
        return "••••"
    return f"{api_key[:3]}…{api_key[-4:]}"


def enforce_verification_rate_limit(user_id: UUID) -> None:
    now = monotonic()
    key = str(user_id)
    with _verification_lock:
        calls = _verification_calls[key]
        while calls and now - calls[0] >= VERIFY_WINDOW_SECONDS:
            calls.popleft()
        if len(calls) >= VERIFY_LIMIT:
            raise AppError(
                429,
                "MODEL_CREDENTIAL_RATE_LIMITED",
                "模型密钥验证过于频繁，请稍后再试",
            )
        calls.append(now)


async def verify_api_key(
    provider: str,
    api_key: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> None:
    definition = get_provider_definition(provider)
    model = model_config(
        definition,
        SecretStr(api_key),
        key_source="user",
    )
    payload = {
        "model": model.id,
        "stream": False,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "回复 OK"}],
        **model.extra_payload,
    }
    timeout = httpx.Timeout(
        min(get_settings().ai_timeout_seconds, VERIFY_TIMEOUT_SECONDS),
        connect=VERIFY_TIMEOUT_SECONDS,
    )
    owns_client = client is None
    active_client = client or httpx.AsyncClient(timeout=timeout)
    try:
        try:
            response = await active_client.post(
                chat_completions_url(model.base_url),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise AppError(
                504,
                "MODEL_CREDENTIAL_VERIFY_TIMEOUT",
                "模型服务验证超时，请稍后重试",
            ) from exc
        except httpx.HTTPError as exc:
            raise AppError(
                502,
                "MODEL_CREDENTIAL_VERIFY_UNAVAILABLE",
                "暂时无法连接模型服务验证密钥",
            ) from exc
    finally:
        if owns_client:
            await active_client.aclose()
    if response.status_code >= 500:
        raise AppError(
            502,
            "MODEL_CREDENTIAL_VERIFY_UNAVAILABLE",
            "模型服务暂时无法完成密钥验证",
        )
    if not 200 <= response.status_code < 300:
        raise AppError(
            422,
            "MODEL_CREDENTIAL_INVALID",
            "API Key 无效、无权限或当前不可用",
        )


def credential_out(row: UserModelCredential) -> ModelCredentialOut:
    return ModelCredentialOut(
        provider=row.provider,
        masked_key=mask_api_key(decrypt_sensitive(row.api_key_ciphertext)),
        updated_at=row.updated_at,
        last_verified_at=row.last_verified_at,
    )


async def list_credentials(db: AsyncSession, user_id: UUID) -> list[ModelCredentialOut]:
    rows = (
        await db.scalars(
            select(UserModelCredential)
            .where(UserModelCredential.user_id == user_id)
            .order_by(UserModelCredential.provider)
        )
    ).all()
    return [credential_out(row) for row in rows]


async def put_credential(
    db: AsyncSession,
    user_id: UUID,
    provider: str,
    api_key: str,
) -> ModelCredentialOut:
    get_provider_definition(provider)
    enforce_verification_rate_limit(user_id)
    await verify_api_key(provider, api_key)
    now = datetime.now(UTC)
    ciphertext = encrypt_sensitive(api_key)
    statement = (
        insert(UserModelCredential)
        .values(
            user_id=user_id,
            provider=provider,
            api_key_ciphertext=ciphertext,
            last_verified_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_user_model_credentials_user_provider",
            set_={
                "api_key_ciphertext": ciphertext,
                "last_verified_at": now,
                "updated_at": now,
            },
        )
    )
    await db.execute(statement)
    await db.commit()
    row = await db.scalar(
        select(UserModelCredential).where(
            UserModelCredential.user_id == user_id,
            UserModelCredential.provider == provider,
        )
    )
    assert row is not None
    return credential_out(row)


async def delete_credential(db: AsyncSession, user_id: UUID, provider: str) -> None:
    get_provider_definition(provider)
    await db.execute(
        delete(UserModelCredential).where(
            UserModelCredential.user_id == user_id,
            UserModelCredential.provider == provider,
        )
    )
    await db.commit()


async def available_models_for_user(db: AsyncSession, user_id: UUID) -> list[ModelConfig]:
    rows = (
        await db.scalars(select(UserModelCredential).where(UserModelCredential.user_id == user_id))
    ).all()
    user_keys = {row.provider: row for row in rows}
    settings = get_settings()
    models: list[ModelConfig] = []
    for definition in MODEL_DEFINITIONS:
        credential = user_keys.get(definition.provider)
        if credential is not None:
            models.append(
                model_config(
                    definition,
                    SecretStr(decrypt_sensitive(credential.api_key_ciphertext)),
                    settings=settings,
                    key_source="user",
                )
            )
            continue
        server_key = getattr(settings, definition.api_key_setting)
        if server_key and server_key.get_secret_value().strip():
            models.append(model_config(definition, server_key, settings=settings))
    return models


async def get_model_for_user(db: AsyncSession, user_id: UUID, model_id: str) -> ModelConfig:
    get_model_definition(model_id)
    model = next(
        (item for item in await available_models_for_user(db, user_id) if item.id == model_id),
        None,
    )
    if model is None:
        raise AppError(422, "MODEL_NOT_AVAILABLE", "所选模型不存在或尚未配置")
    return model


async def preferred_model_for_user(db: AsyncSession, user_id: UUID) -> ModelConfig | None:
    models = await available_models_for_user(db, user_id)
    return models[0] if models else None
