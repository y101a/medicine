import logging
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.ai.mcp.server import MCPApplicationSlot, build_medical_mcp_server
from app.api.router import api_router
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.voice_upload_middleware import (
    VoiceUploadBodyLimitMiddleware,
    configure_voice_multipart_memory,
)
from app.db.session import engine

logging.getLogger("httpx").setLevel(logging.WARNING)

settings = get_settings()
configure_voice_multipart_memory(settings.asr_max_bytes)
mcp_enabled = settings.app_environment == "development" and settings.mcp_enabled
mcp_slot = MCPApplicationSlot()


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with AsyncExitStack() as stack:
        if mcp_enabled:
            mcp_server = build_medical_mcp_server(settings)
            mcp_slot.application = mcp_server.streamable_http_app(
                streamable_http_path="/",
                json_response=True,
                stateless_http=True,
                host="127.0.0.1",
            )
            await stack.enter_async_context(mcp_server.session_manager.run())
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        try:
            yield
        finally:
            mcp_slot.application = None
            await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
    docs_url=f"{settings.api_v1_prefix}/docs",
    openapi_url=f"{settings.api_v1_prefix}/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    VoiceUploadBodyLimitMiddleware,
    max_audio_bytes=settings.asr_max_bytes,
    path=f"{settings.api_v1_prefix}/voice/transcribe",
)
app.include_router(api_router, prefix=settings.api_v1_prefix)
if mcp_enabled:
    app.mount("/mcp", mcp_slot, name="mcp")


@app.exception_handler(AppError)
async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message, "details": exc.details},
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    details: list[dict[str, Any]] = []
    for error in exc.errors():
        details.append(
            {
                "field": ".".join(str(part) for part in error["loc"] if part != "body"),
                "message": error["msg"],
            }
        )
    return JSONResponse(
        status_code=422,
        content={
            "code": "VALIDATION_ERROR",
            "message": "提交的信息校验未通过",
            "details": details,
        },
    )
