import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from cryptography.fernet import Fernet, InvalidToken
from pwdlib import PasswordHash

from app.core.config import get_settings

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded_hash: str) -> bool:
    return password_hash.verify(password, encoded_hash)


def create_access_token(user_id: UUID, auth_version: int = 1) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "type": "access",
        "ver": auth_version,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")


def decode_access_token(token: str) -> UUID:
    user_id, _ = decode_access_token_with_version(token)
    return user_id


def decode_access_token_with_version(token: str) -> tuple[UUID, int]:
    settings = get_settings()
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Unexpected token type")
    version = payload.get("ver")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise jwt.InvalidTokenError("Invalid authentication version")
    return UUID(payload["sub"]), version


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def encrypt_sensitive(value: str) -> str:
    settings = get_settings()
    return (
        Fernet(settings.field_encryption_key.encode("ascii"))
        .encrypt(value.encode("utf-8"))
        .decode("ascii")
    )


def decrypt_sensitive(value: str) -> str:
    settings = get_settings()
    try:
        return (
            Fernet(settings.field_encryption_key.encode("ascii"))
            .decrypt(value.encode("ascii"))
            .decode("utf-8")
        )
    except InvalidToken as exc:
        raise ValueError("Sensitive field cannot be decrypted") from exc


def sensitive_fingerprint(value: str) -> str:
    settings = get_settings()
    return hmac.new(
        settings.fingerprint_secret.encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
