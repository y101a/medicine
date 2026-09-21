import asyncio
from dataclasses import dataclass
from io import BytesIO

import av
from fastapi import UploadFile

from app.core.errors import AppError

WEBM_MAGIC = b"\x1a\x45\xdf\xa3"
DURATION_TOLERANCE_SECONDS = 0.5


@dataclass(frozen=True)
class ValidatedAudio:
    content: bytes
    mime_type: str
    duration_ms: int


def _unsupported_type() -> AppError:
    return AppError(
        415,
        "VOICE_TYPE_NOT_ALLOWED",
        "录音仅支持 WebM/Opus 格式，可改用输入法语音输入",
    )


def _validate_webm_opus(
    content: bytes,
    *,
    max_seconds: float,
) -> ValidatedAudio:
    if not content.startswith(WEBM_MAGIC) or b"webm" not in content[:512].lower():
        raise _unsupported_type()

    try:
        with av.open(BytesIO(content), mode="r") as container:
            audio_streams = list(container.streams.audio)
            if len(audio_streams) != 1 or container.streams.video:
                raise _unsupported_type()
            stream = audio_streams[0]
            if stream.codec_context.name != "opus":
                raise _unsupported_type()

            duration_seconds = 0.0
            decoded_frames = 0
            for frame in container.decode(stream):
                if not frame.sample_rate or frame.samples <= 0:
                    continue
                decoded_frames += 1
                duration_seconds += frame.samples / frame.sample_rate
                if duration_seconds > max_seconds + DURATION_TOLERANCE_SECONDS:
                    raise AppError(
                        422,
                        "VOICE_TOO_LONG",
                        f"单次录音不能超过 {max_seconds:g} 秒",
                    )
    except AppError:
        raise
    except (av.FFmpegError, EOFError, OSError, ValueError) as exc:
        raise AppError(422, "VOICE_INVALID_AUDIO", "录音文件已损坏或内容无效") from exc

    if decoded_frames == 0 or duration_seconds <= 0:
        raise AppError(422, "VOICE_INVALID_AUDIO", "录音文件已损坏或内容无效")
    return ValidatedAudio(
        content=content,
        mime_type="audio/webm",
        duration_ms=max(1, round(duration_seconds * 1000)),
    )


async def read_and_validate_audio(
    upload: UploadFile,
    *,
    max_bytes: int,
    max_seconds: float,
) -> ValidatedAudio:
    if bool(getattr(upload.file, "_rolled", False)):
        await upload.close()
        raise AppError(413, "VOICE_TOO_LARGE", "单次录音不能超过 2 MB")
    try:
        content = await upload.read(max_bytes + 1)
    finally:
        await upload.close()

    if len(content) > max_bytes:
        limit_mb = max_bytes / (1024 * 1024)
        raise AppError(
            413,
            "VOICE_TOO_LARGE",
            f"单次录音不能超过 {limit_mb:g} MB",
        )
    if not content:
        raise AppError(422, "VOICE_INVALID_AUDIO", "录音内容为空或无效")
    return await asyncio.to_thread(
        _validate_webm_opus,
        content,
        max_seconds=max_seconds,
    )
