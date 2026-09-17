import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Query, Response
from fastapi.responses import StreamingResponse

from app.ai import provider
from app.ai.follow_up import (
    FOLLOW_UP_PREFIX,
    is_follow_up_prefix_fragment,
    parse_follow_up,
    serialize_follow_up,
    split_follow_up_content,
)
from app.ai.graph import render_rag_context, run_consultation_generation
from app.ai.registry import get_model
from app.api.dependencies import CurrentUser, DbSession
from app.core.errors import AppError
from app.rag.citation_audit import audit_answer_citations
from app.rag.web_search import broad_coverage_limited, generic_topic
from app.schemas.consultations import (
    ConsultationOut,
    ConsultationPage,
    CreateConsultation,
    CreateGeneration,
    CreateMessage,
    MessageOut,
    MessagePage,
)
from app.services import consultations as service
from app.services import health_records as health_service

router = APIRouter(prefix="/consultations", tags=["咨询"])


@router.post("", response_model=ConsultationOut, status_code=201)
async def create_consultation(payload: CreateConsultation, user: CurrentUser, db: DbSession):
    return await service.create(db, user.id, payload.client_request_id)


@router.get("", response_model=ConsultationPage)
async def get_consultations(
    user: CurrentUser,
    db: DbSession,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    return await service.list_consultations(db, user.id, offset, limit)


@router.get("/{cid}", response_model=ConsultationOut)
async def get_consultation(cid: UUID, user: CurrentUser, db: DbSession):
    return service.summary(await service.owned(db, user.id, cid))


@router.get("/{cid}/messages", response_model=MessagePage)
async def get_messages(
    cid: UUID,
    user: CurrentUser,
    db: DbSession,
    before: int | None = Query(None, ge=1),
    limit: int = Query(50, ge=1, le=100),
):
    return await service.list_messages(db, user.id, cid, before, limit)


@router.post("/{cid}/messages", response_model=MessageOut, status_code=201)
async def post_message(cid: UUID, payload: CreateMessage, user: CurrentUser, db: DbSession):
    return await service.append_message(db, user.id, cid, payload)


@router.post("/{cid}/stream")
async def stream_answer(cid: UUID, payload: CreateGeneration, user: CurrentUser, db: DbSession):
    triage = await service.pending_triage(db, user.id, cid)
    if triage:
        raise AppError(
            409,
            "EMERGENCY_TRIAGE_ACTIVE",
            "当前消息命中紧急分流规则，请优先拨打 120，不再生成普通 AI 回答",
        )
    model = get_model(payload.model_id)
    source_message_id = getattr(payload, "source_message_id", None)
    if source_message_id is not None:
        if payload.answer_format != "card":
            raise AppError(
                422,
                "PATHOLOGY_CARD_FORMAT_REQUIRED",
                "基于原回答追加生成时必须使用病理科普卡片格式",
            )
        history, user_text = await service.card_generation_history(
            db,
            user.id,
            cid,
            source_message_id,
        )
    else:
        history, _ = await service.ai_history(db, user.id, cid)
        user_text = history[-1]["content"]
    graph_result = await run_consultation_generation(user_text, db)
    if graph_result["triage_route"] == "emergency":
        raise AppError(
            409,
            "EMERGENCY_TRIAGE_ACTIVE",
            "当前消息命中紧急分流规则，请优先拨打 120，不再生成普通 AI 回答",
        )
    # 用户自述健康记录：只用于避免重复询问、贴合科普与提醒就医；
    # 上面的紧急分流完全不依赖它。
    health_context = await health_service.build_health_context(db, user.id)
    rag_context = render_rag_context(graph_result["retrieval_items"])
    topic = generic_topic(user_text)
    coverage_limited = bool(
        graph_result["retrieval_items"]
        and broad_coverage_limited(
            topic,
            [item["title"] + item["content"] for item in graph_result["retrieval_items"]],
        )
    )
    citation_snapshots: list[dict] = []
    for index, item in enumerate(graph_result["retrieval_items"], start=1):
        citation_snapshots.append(
            {
                "reference_number": index,
                "source_key": item["source_key"],
                "organization": item["organization"],
                "title": item["title"],
                "canonical_url": item["canonical_url"],
                "section_title": item["section_title"],
                "similarity": item["similarity"],
                "trust_level": item["trust_level"],
            }
        )
    await db.commit()

    def encode(event: dict) -> str:
        return json.dumps(event, ensure_ascii=False, default=str) + "\n"

    async def generate():
        parts: list[str] = []
        pending = ""
        follow_up_payload: str | None = None
        total_length = 0
        yield encode(
            {
                "type": "start",
                "model": {
                    "id": model.id,
                    "name": model.name,
                    "provider": model.provider,
                },
                "retrieval": {
                    "status": graph_result["retrieval_status"],
                    "gateReason": graph_result["retrieval_gate_reason"],
                    "webSearchStatus": graph_result["web_search_status"],
                    "webSearchErrorCode": graph_result["web_search_error_code"],
                    "coverageLimited": coverage_limited,
                    "errorCode": graph_result["retrieval_error_code"],
                    "sources": [
                        {
                            "referenceNumber": item["reference_number"],
                            "sourceKey": item["source_key"],
                            "organization": item["organization"],
                            "title": item["title"],
                            "canonicalUrl": item["canonical_url"],
                            "sectionTitle": item["section_title"],
                            "similarity": item["similarity"],
                            "trustLevel": item["trust_level"],
                        }
                        for item in citation_snapshots
                    ],
                },
            }
        )
        try:
            async for chunk in provider.stream_chat(
                history,
                model,
                payload.answer_format,
                rag_context,
                health_context,
            ):
                remaining = 12000 - total_length
                if remaining <= 0:
                    break
                chunk = chunk[:remaining]
                total_length += len(chunk)
                if follow_up_payload is not None:
                    follow_up_payload += chunk
                    continue
                pending += chunk
                while pending:
                    split = split_follow_up_content(pending)
                    if split is not None:
                        visible, follow_up_payload = split
                        pending = ""
                        if visible:
                            parts.append(visible)
                            yield encode({"type": "delta", "content": visible})
                        break
                    marker_start = pending.find("[[")
                    if marker_start < 0:
                        visible, pending = pending, ""
                    elif marker_start > 0:
                        visible, pending = pending[:marker_start], pending[marker_start:]
                    elif is_follow_up_prefix_fragment(pending):
                        break
                    else:
                        next_marker = pending.find("[[", 2)
                        if next_marker < 0:
                            visible, pending = pending, ""
                        else:
                            visible, pending = pending[:next_marker], pending[next_marker:]
                    parts.append(visible)
                    yield encode({"type": "delta", "content": visible})
            if follow_up_payload is not None:
                card = parse_follow_up(
                    FOLLOW_UP_PREFIX + follow_up_payload,
                    strict=True,
                )
                content = serialize_follow_up(card)
            else:
                if pending:
                    parts.append(pending)
                    yield encode({"type": "delta", "content": pending})
                content = "".join(parts)
            if follow_up_payload is None:
                content, verified_citations = audit_answer_citations(
                    content, citation_snapshots
                )
            else:
                verified_citations = []
            message = await service.append_assistant_message(
                db,
                user.id,
                cid,
                payload.client_request_id,
                content,
                model.provider,
                model.id,
                model.name,
                citations=verified_citations,
                answer_format=payload.answer_format,
                medical_content=(
                    graph_result["retrieval_gate_reason"] == "medical_content"
                ),
                source_message_id=source_message_id,
            )
            yield encode(
                {"type": "done", "message": message.model_dump(by_alias=True, mode="json")}
            )
        except asyncio.CancelledError:
            if parts:
                try:
                    checked, verified_citations = audit_answer_citations(
                        "".join(parts), citation_snapshots
                    )
                    await service.append_assistant_message(
                        db,
                        user.id,
                        cid,
                        payload.client_request_id,
                        checked + "\n\n（回答已停止生成）",
                        model.provider,
                        model.id,
                        model.name,
                        generation_status="stopped",
                        citations=verified_citations,
                        answer_format=payload.answer_format,
                        medical_content=(
                            graph_result["retrieval_gate_reason"] == "medical_content"
                        ),
                        source_message_id=None,
                    )
                except Exception:
                    await db.rollback()
            raise
        except Exception as exc:
            await db.rollback()
            if parts:
                try:
                    checked, verified_citations = audit_answer_citations(
                        "".join(parts), citation_snapshots
                    )
                    await service.append_assistant_message(
                        db,
                        user.id,
                        cid,
                        payload.client_request_id,
                        checked + "\n\n（回答因服务异常中断）",
                        model.provider,
                        model.id,
                        model.name,
                        generation_status="failed",
                        citations=verified_citations,
                        answer_format=payload.answer_format,
                        medical_content=(
                            graph_result["retrieval_gate_reason"] == "medical_content"
                        ),
                        source_message_id=None,
                    )
                except Exception:
                    await db.rollback()
            message = exc.message if hasattr(exc, "message") else "AI 回答生成失败，请稍后重试"
            code = exc.code if hasattr(exc, "code") else "AI_GENERATION_FAILED"
            yield encode({"type": "error", "code": code, "message": message})

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/{cid}", status_code=204)
async def delete_consultation(cid: UUID, user: CurrentUser, db: DbSession):
    await service.remove(db, user.id, cid)
    return Response(status_code=204)
