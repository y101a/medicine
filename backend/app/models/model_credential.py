import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserModelCredential(Base):
    __tablename__ = "user_model_credentials"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    provider: Mapped[str] = mapped_column(String(32))
    api_key_ciphertext: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "provider IN ('deepseek', 'qwen', 'kimi', 'zhipuai')",
            name="provider_supported",
        ),
        UniqueConstraint(
            "user_id", "provider", name="uq_user_model_credentials_user_provider"
        ),
        Index("ix_user_model_credentials_user_id", "user_id"),
    )
