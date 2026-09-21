import logging
from typing import Annotated

from fastapi import APIRouter, File, Response, UploadFile
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.errors import AppError
from app.schemas.voice import VoiceTranscriptionOut
from app.services.audio_validation import read_and_validate_audio
from app.services.audit_logs import (
    AUDIT_OUTCOME_REJECTED,
    AUDIT_OUTCOME_SUCCESS,
    add_audit_log,
)
from app.services.upload_limits import enforce_upload_rate_limit
from app.services.voice_transcription import transcribe_audio

router = APIRouter(prefix="/voice", tags=["语音输入"])
logger = logging.getLogger(__name__)


async def _record_rejection(db: DbSession, user: CurrentUser, reason_code: str) -> None:
    try:
        await add_audit_log(
            db,
            actor_user_id=user.id,
            action="transcribe",
            resource_type="voice_audio",
            outcome=AUDIT_OUTCOME_REJECTED,
            reason_code=reason_code,
        )
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        logger.exception("Failed to persist rejected voice transcription audit event")


@router.post(
    "/transcribe",
    response_model=VoiceTranscriptionOut,
    summary="将单段录音转为待用户核对的文字",
)
async def transcribe_voice(
    current_user: CurrentUser,
    db: DbSession,
    response: Response,
    audio: Annotated[UploadFile, File()],
) -> VoiceTranscriptionOut:
    settings = get_settings()
    try:
        enforce_upload_rate_limit(current_user.id, "voice_audio")
        validated = await read_and_validate_audio(
            audio,
            max_bytes=settings.asr_max_bytes,
            max_seconds=settings.asr_max_seconds,
        )
        text = await transcribe_audio(validated, settings=settings)
    except AppError as exc:
        if exc.code != "UPLOAD_RATE_LIMITED":
            await _record_rejection(db, current_user, exc.code)
        raise

    await add_audit_log(
        db,
        actor_user_id=current_user.id,
        action="transcribe",
        resource_type="voice_audio",
        outcome=AUDIT_OUTCOME_SUCCESS,
    )
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return VoiceTranscriptionOut(text=text, duration_ms=validated.duration_ms)
