from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class KnowledgeSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=2000)
    top_k: int = Field(default=5, alias="topK", ge=1, le=10)

    @field_validator("query", mode="before")
    @classmethod
    def trim_query(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class KnowledgeCitationOut(BaseModel):
    chunk_id: UUID = Field(serialization_alias="chunkId")
    document_id: UUID = Field(serialization_alias="documentId")
    source_key: str = Field(serialization_alias="sourceKey")
    organization: str
    title: str
    canonical_url: str = Field(serialization_alias="canonicalUrl")
    section_title: str | None = Field(serialization_alias="sectionTitle")
    version_label: str | None = Field(serialization_alias="versionLabel")
    published_at: datetime | None = Field(serialization_alias="publishedAt")
    content: str
    similarity: float
    trust_level: str = Field(serialization_alias="trustLevel")


class KnowledgeSearchResponse(BaseModel):
    query_redacted: bool = Field(serialization_alias="queryRedacted")
    embedding_model: str = Field(serialization_alias="embeddingModel")
    embedding_version: str = Field(serialization_alias="embeddingVersion")
    items: list[KnowledgeCitationOut]
