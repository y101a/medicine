
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MULTIPART_OVERHEAD_BYTES = 64 * 1024


class VoiceBodyTooLarge(Exception):
    pass


class VoiceUploadBodyLimitMiddleware:
    """Reject oversized voice bodies before Starlette's multipart parser runs."""

    def __init__(self, app: ASGIApp, *, max_audio_bytes: int, path: str) -> None:
        self.app = app
        self.path = path
        self.max_audio_bytes = max_audio_bytes
        self.max_body_bytes = max_audio_bytes + MULTIPART_OVERHEAD_BYTES

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        limit_mb = self.max_audio_bytes / (1024 * 1024)
        response = JSONResponse(
            status_code=413,
            content={
                "code": "VOICE_TOO_LARGE",
                "message": f"单次录音不能超过 {limit_mb:g} MB",
                "details": None,
            },
        )
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path") != self.path
        ):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        raw_length = headers.get(b"content-length")
        if raw_length:
            try:
                if int(raw_length) > self.max_body_bytes:
                    await self._reject(scope, receive, send)
                    return
            except ValueError:
                await self._reject(scope, receive, send)
                return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                received += len(body)
                if received > self.max_body_bytes:
                    raise VoiceBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except VoiceBodyTooLarge:
            await self._reject(scope, receive, send)


def configure_voice_multipart_memory(max_audio_bytes: int) -> None:
    """Keep every request accepted by the voice body limit out of temp files."""
    from starlette.formparsers import MultiPartParser

    required = max_audio_bytes + MULTIPART_OVERHEAD_BYTES + 1
    MultiPartParser.spool_max_size = max(MultiPartParser.spool_max_size, required)
