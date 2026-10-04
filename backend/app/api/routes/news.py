"""Authenticated news portal shell; no sources, fetching, or sample articles yet."""

from fastapi import APIRouter, Depends

from app.api.dependencies import get_current_user
from app.schemas.news import NewsCategory, NewsPageOut

router = APIRouter(
    prefix="/news", tags=["健康资讯"], dependencies=[Depends(get_current_user)]
)


@router.get("", response_model=NewsPageOut)
async def read_news(category: NewsCategory = "all") -> NewsPageOut:
    return NewsPageOut(category=category, status="sources_not_connected")
