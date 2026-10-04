"""Read-only health news portal contract; ingestion is intentionally not connected yet."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

NewsCategory = Literal["all", "wellness", "fitness", "disease", "medication"]
NewsItemCategory = Literal["wellness", "fitness", "disease", "medication"]


class NewsItemOut(BaseModel):
    id: str
    category: NewsItemCategory
    title: str
    summary: str
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


class NewsPageOut(BaseModel):
    category: NewsCategory
    status: Literal["sources_not_connected"]
    as_of: datetime | None = Field(default=None, serialization_alias="asOf")
    items: list[NewsItemOut] = Field(default_factory=list)
    tips: list[NewsTipOut] = Field(default_factory=list)
