import re

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MULTIPART_OVERHEAD_BYTES = 64 * 1024


class AttachmentBodyTooLarge(Exception):
    pass


class AttachmentUploadBodyLimitMiddleware:
    """Reject oversized document bodies before Starlette can spool multipart data."""

    def __init__(self, app: ASGIApp, *, max_file_bytes: int, path_pattern: str) -> None:
        self.app = app
        self.path_pattern = re.compile(path_pattern)
        self.max_file_bytes = max_file_bytes
        self.max_body_bytes = max_file_bytes + MULTIPART_OVERHEAD_BYTES

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        limit_mb = self.max_file_bytes / (1024 * 1024)
        response = JSONResponse(
            status_code=413,
            content={
                "code": "FILE_TOO_LARGE",
                "message": f"单个文档不能超过 {limit_mb:g} MB",
                "details": None,
            },
        )
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or self.path_pattern.fullmatch(path) is None
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
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    raise AttachmentBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except AttachmentBodyTooLarge:
            await self._reject(scope, receive, send)


def configure_attachment_multipart_memory(max_file_bytes: int) -> None:
    """Keep requests accepted by the document body limit out of temporary files."""
    from starlette.formparsers import MultiPartParser

    required = max_file_bytes + MULTIPART_OVERHEAD_BYTES + 1
    MultiPartParser.spool_max_size = max(MultiPartParser.spool_max_size, required)
