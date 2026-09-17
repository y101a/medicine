from __future__ import annotations

import json
import logging
from time import monotonic
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from app.ai.mcp.amap import (
    find_nearby_hospitals,
    search_hospitals_by_area,
    search_medical_pois,
)
from app.ai.mcp.models import AmapPoiResult, NearbyHospitalResult, PubMedSearchResult
from app.ai.mcp.pubmed import search_pubmed
from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)
READ_ONLY_OPEN_WORLD = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)


def _secret_value(secret: Any) -> str | None:
    if secret is None:
        return None
    value = secret.get_secret_value().strip()
    return value or None


def _audit(tool: str, started_at: float, outcome: str, count: int | None = None) -> None:
    payload: dict[str, object] = {
        "event": "mcp_tool_call",
        "tool": tool,
        "outcome": outcome,
        "duration_ms": round((monotonic() - started_at) * 1000),
    }
    if count is not None:
        payload["result_count"] = count
    logger.info("%s", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def build_medical_mcp_server(settings: Settings | None = None) -> MCPServer:
    active_settings = settings or get_settings()
    server = MCPServer(
        name="medical-assistant-readonly",
        instructions=(
            "只读外部资料工具。PubMed 仅接受固定通用病名；高德仅接受城市或行政区编码与"
            "通用科室。附近医院工具只有在调用方已取得用户本次明确定位授权时才接受坐标；"
            "坐标不得保存或写入日志。不得提交姓名、电话、证件号、详细住址或患者病情原文。"
        ),
    )

    @server.tool(
        name="search_pubmed",
        description="按系统白名单中的通用病名检索 PubMed 最新文献元数据和摘要。",
        annotations=READ_ONLY_OPEN_WORLD,
        structured_output=True,
    )
    async def pubmed_tool(topic: str, max_results: int = 5) -> PubMedSearchResult:
        started_at = monotonic()
        try:
            result = await search_pubmed(
                topic,
                max_results=max_results,
                api_key=_secret_value(active_settings.pubmed_api_key),
                tool_name=active_settings.pubmed_tool_name,
                email=active_settings.pubmed_email,
                timeout_seconds=active_settings.external_tool_timeout_seconds,
            )
        except Exception:
            _audit("search_pubmed", started_at, "failed")
            raise
        _audit("search_pubmed", started_at, "succeeded", result.count)
        return result

    @server.tool(
        name="search_medical_pois",
        description="按城市或 6 位行政区编码和通用科室检索高德公开医疗 POI；不接收坐标。",
        annotations=READ_ONLY_OPEN_WORLD,
        structured_output=True,
    )
    async def amap_tool(
        city: str,
        department: str,
        max_results: int = 5,
    ) -> AmapPoiResult:
        started_at = monotonic()
        try:
            result = await search_medical_pois(
                city,
                department,
                max_results=max_results,
                api_key=_secret_value(active_settings.amap_api_key),
                timeout_seconds=active_settings.external_tool_timeout_seconds,
            )
        except Exception:
            _audit("search_medical_pois", started_at, "failed")
            raise
        _audit("search_medical_pois", started_at, "succeeded", result.count)
        return result

    @server.tool(
        name="find_nearby_hospitals",
        description=(
            "取得用户本次明确定位授权后，按驾车或步行路线耗时比较附近最多三家医院；"
            "不得保存或记录坐标。"
        ),
        annotations=READ_ONLY_OPEN_WORLD,
        structured_output=True,
    )
    async def nearby_hospitals_tool(
        latitude: float,
        longitude: float,
        location_consent: bool,
        route_mode: str = "driving",
        max_results: int = 3,
    ) -> NearbyHospitalResult:
        started_at = monotonic()
        try:
            result = await find_nearby_hospitals(
                latitude,
                longitude,
                route_mode=route_mode,
                max_results=max_results,
                location_consent=location_consent,
                api_key=_secret_value(active_settings.amap_api_key),
                timeout_seconds=active_settings.external_tool_timeout_seconds,
            )
        except Exception:
            _audit("find_nearby_hospitals", started_at, "failed")
            raise
        _audit("find_nearby_hospitals", started_at, "succeeded", result.count)
        return result

    @server.tool(
        name="search_hospitals_by_area",
        description="定位被拒绝或失败时，按城市或 6 位行政区编码返回医院列表。",
        annotations=READ_ONLY_OPEN_WORLD,
        structured_output=True,
    )
    async def hospitals_by_area_tool(
        city: str,
        max_results: int = 5,
    ) -> AmapPoiResult:
        started_at = monotonic()
        try:
            result = await search_hospitals_by_area(
                city,
                max_results=max_results,
                api_key=_secret_value(active_settings.amap_api_key),
                timeout_seconds=active_settings.external_tool_timeout_seconds,
            )
        except Exception:
            _audit("search_hospitals_by_area", started_at, "failed")
            raise
        _audit("search_hospitals_by_area", started_at, "succeeded", result.count)
        return result

    return server


class MCPApplicationSlot:
    """ASGI mount whose target is refreshed for every parent app lifespan."""

    def __init__(self) -> None:
        self.application: Any = None

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if self.application is None:
            raise RuntimeError("MCP_NOT_RUNNING")
        await self.application(scope, receive, send)
