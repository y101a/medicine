"""Inject a reviewed generated-image summary only for explicit follow-up questions."""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt_sensitive
from app.models import GeneratedImage

_REFERENCE = re.compile(r"(这|那|刚才|上面|前面).{0,5}(张)?(图|图片)|图里|图中|生成的图")


async def build_generated_image_context(
    db: AsyncSession,
    *,
    user_id: UUID,
    consultation_id: UUID,
    question: str,
) -> str | None:
    if not _REFERENCE.search(question):
        return None
    row = await db.scalar(
        select(GeneratedImage)
        .where(
            GeneratedImage.user_id == user_id,
            GeneratedImage.consultation_id == consultation_id,
            GeneratedImage.status == "completed",
            GeneratedImage.review_summary_ciphertext.is_not(None),
        )
        .order_by(GeneratedImage.completed_at.desc(), GeneratedImage.id.desc())
        .limit(1)
    )
    if row is None or not row.review_summary_ciphertext:
        return None
    summary = decrypt_sensitive(row.review_summary_ciphertext)
    return (
        "【最近一张 AI 科普配图的视觉复核摘要】\n"
        f"{summary}\n"
        "该摘要来自模型对生成图像素的非诊断性复核，只能用于解释图中可见内容；"
        "不得据此确诊、补充未见事实或替代医学资料。"
    )
