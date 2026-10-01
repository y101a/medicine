import logging
from time import monotonic
from uuid import UUID

from fastapi import APIRouter, Response
from sqlalchemy import select

from app.api.dependencies import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.errors import AppError
from app.models import Consultation, Message
from app.schemas.speech import (
    SpeechPreset,
    SpeechPresetListOut,
    SpeechSynthesisRequest,
)
from app.services import consultations as consultation_service
from app.services.audit_logs import (
    AUDIT_OUTCOME_REJECTED,
    AUDIT_OUTCOME_SUCCESS,
    add_audit_log,
)
from app.services.speech_limits import enforce_speech_limits
from app.services.speech_synthesis import list_speech_presets, synthesize_speech
from app.services.speech_text import prepare_speech_text

router = APIRouter(tags=["语音输出"])
logger = logging.getLogger(__name__)


@router.get("/speech/presets", response_model=SpeechPresetListOut)
async def get_speech_presets(_: CurrentUser) -> SpeechPresetListOut:
    return list_speech_presets()


async def _owned_assistant_message(
    db: DbSession,
    *,
    user_id: UUID,
    consultation_id: UUID,
    message_id: UUID,
) -> Message:
    row = await db.scalar(
        select(Message)
        .join(Consultation, Consultation.id == Message.consultation_id)
        .where(
            Message.id == message_id,
            Message.consultation_id == consultation_id,
            Consultation.user_id == user_id,
        )
    )
    if row is None:
        raise AppError(404, "SPEECH_MESSAGE_NOT_FOUND", "没有找到可朗读的回答")
    if row.role != "assistant":
        raise AppError(422, "SPEECH_MESSAGE_UNSUPPORTED", "这条内容暂时无法朗读")
    if row.generation_status != "completed":
        raise AppError(409, "SPEECH_MESSAGE_NOT_READY", "回答尚未完成，请稍后再试")
    return row


@router.post("/consultations/{cid}/messages/{message_id}/speech")
async def create_message_speech(
    cid: UUID,
    message_id: UUID,
    payload: SpeechSynthesisRequest,
    user: CurrentUser,
    db: DbSession,
) -> Response:
    row = await _owned_assistant_message(
        db,
        user_id=user.id,
        consultation_id=cid,
        message_id=message_id,
    )
    settings = get_settings()
    visible_content = consultation_service.message_out(row).content
    speech_text = prepare_speech_text(
        visible_content,
        max_chars=settings.tts_max_text_chars,
    )
    try:
        preset = SpeechPreset(payload.speech_preset)
    except ValueError:
        raise AppError(
            422,
            "SPEECH_PRESET_UNSUPPORTED",
            "暂不支持这个音色或方言",
        ) from None
    await enforce_speech_limits(db, user_id=user.id, message_id=row.id)

    started = monotonic()
    try:
        audio = await synthesize_speech(
            speech_text,
            preset=preset,
            rate=payload.rate,
            settings=settings,
        )
    except AppError as exc:
        await add_audit_log(
            db,
            actor_user_id=user.id,
            action="synthesize",
            resource_type="voice_output",
            resource_id=row.id,
            outcome=AUDIT_OUTCOME_REJECTED,
            reason_code=exc.code,
        )
        await db.commit()
        logger.info(
            "speech_synthesis_failed preset=%s chars=%d elapsed_ms=%d code=%s",
            preset.value,
            len(speech_text),
            round((monotonic() - started) * 1000),
            exc.code,
        )
        raise

    await add_audit_log(
        db,
        actor_user_id=user.id,
        action="synthesize",
        resource_type="voice_output",
        resource_id=row.id,
        outcome=AUDIT_OUTCOME_SUCCESS,
    )
    await db.commit()
    logger.info(
        "speech_synthesis_succeeded preset=%s chars=%d bytes=%d elapsed_ms=%d request_id=%s",
        preset.value,
        len(speech_text),
        len(audio.content),
        round((monotonic() - started) * 1000),
        audio.request_id,
    )
    return Response(
        content=audio.content,
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'inline; filename="assistant-speech.mp3"',
            "X-Speech-Preset": preset.value,
            "X-Request-Id": audio.request_id,
        },
    )
