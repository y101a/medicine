"""Read-only health news portal contract.

资讯只读最近成功快照：没有来源时明确回 `sources_not_connected`，绝不伪造条目。
来源级状态是受控码，不回传原始异常、页面 HTML 或抓取日志（`NEWS_UPDATE_PLAN.md` §3）。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

NewsCategory = Literal["all", "wellness", "fitness", "disease", "medication"]
NewsItemCategory = Literal["wellness", "fitness", "disease", "medication"]
NewsStatus = Literal[
    "sources_not_connected", "ready", "partial", "stale", "empty", "failed"
]
NewsSourceStatus = Literal["ready", "empty", "stale", "failed"]


class NewsItemOut(BaseModel):
    id: str
    category: NewsItemCategory
    title: str
    #: 摘要可能为空：写不出可靠摘要时只给标题、来源与链接，不编造内容。
    summary: str | None = None
    source_name: str = Field(serialization_alias="sourceName")
    canonical_url: str = Field(serialization_alias="canonicalUrl")
    published_at: datetime | None = Field(serialization_alias="publishedAt")
    retrieved_at: datetime = Field(serialization_alias="retrievedAt")
    medical_reviewed: bool = Field(default=False, serialization_alias="medicalReviewed")


class NewsTipOut(BaseModel):
    id: str
    category: NewsItemCategory
    text: str
    source_name: str = Field(serialization_alias="sourceName")
    canonical_url: str = Field(serialization_alias="canonicalUrl")


class NewsSourceStatusOut(BaseModel):
    id: str
    name: str
    status: NewsSourceStatus
    last_success_at: datetime | None = Field(default=None, serialization_alias="lastSuccessAt")
    last_error_code: str | None = Field(default=None, serialization_alias="lastErrorCode")


class NewsPageOut(BaseModel):
    category: NewsCategory
    status: NewsStatus
    #: 最近成功快照时间，不是接口调用时间。
    as_of: datetime | None = Field(default=None, serialization_alias="asOf")
    next_refresh_at: datetime | None = Field(default=None, serialization_alias="nextRefreshAt")
    items: list[NewsItemOut] = Field(default_factory=list)
    #: 小贴士与新闻分开治理：这里不把新闻自动改写成建议，未接入就保持为空。
    tips: list[NewsTipOut] = Field(default_factory=list)
    source_statuses: list[NewsSourceStatusOut] = Field(
        default_factory=list, serialization_alias="sourceStatuses"
    )
    total: int = 0
    has_more: bool = Field(default=False, serialization_alias="hasMore")
    #: 是否有一轮自动刷新正在进行（当天首次访问触发；接口不等待它完成）。
    refreshing: bool = False