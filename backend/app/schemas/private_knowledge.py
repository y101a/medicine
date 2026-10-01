from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreatePrivateKnowledgeCollection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=40)
    description: str | None = Field(default=None, max_length=200)

    @field_validator("name", "description", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class UpdatePrivateKnowledgeCollection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=40)
    description: str | None = Field(default=None, max_length=200)

    @field_validator("name", "description", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class PrivateKnowledgeCollectionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    description: str | None = None
    status: Literal["active"] = "active"
    document_count: int = Field(serialization_alias="documentCount", ge=0)
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")


class PrivateKnowledgeCollectionList(BaseModel):
    items: list[PrivateKnowledgeCollectionOut]


PrivateKnowledgeDocumentStatus = Literal[
    "queued", "parsing", "indexing", "ready", "failed", "deleting"
]
PrivateKnowledgeDocumentKind = Literal["pdf", "docx", "pptx", "txt", "md"]


class PrivateKnowledgeDocumentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    collection_id: UUID = Field(serialization_alias="collectionId")
    display_name: str = Field(serialization_alias="displayName")
    kind: PrivateKnowledgeDocumentKind
    byte_size: int = Field(serialization_alias="byteSize", ge=1, le=30 * 1024 * 1024)
    page_count: int | None = Field(default=None, serialization_alias="pageCount")
    char_count: int = Field(serialization_alias="charCount", ge=1, le=500_000)
    chunk_count: int = Field(serialization_alias="chunkCount", ge=0)
    status: PrivateKnowledgeDocumentStatus
    error_code: str | None = Field(default=None, serialization_alias="errorCode")
    parser_version: str = Field(serialization_alias="parserVersion")
    index_version: str = Field(serialization_alias="indexVersion")
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")


class PrivateKnowledgeDocumentList(BaseModel):
    items: list[PrivateKnowledgeDocumentOut]


class PrivateKnowledgeSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2000)
    collection_ids: list[UUID] = Field(
        min_length=1,
        max_length=3,
        alias="collectionIds",
    )
    limit: int = Field(default=5, ge=1, le=5)

    @field_validator("query", mode="before")
    @classmethod
    def trim_query(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("collection_ids")
    @classmethod
    def unique_collections(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("知识库不能重复选择")
        return value


class PrivateKnowledgeSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_number: int = Field(serialization_alias="referenceNumber", ge=1, le=5)
    collection_id: UUID = Field(serialization_alias="collectionId")
    collection_name: str = Field(serialization_alias="collectionName")
    document_id: UUID = Field(serialization_alias="documentId")
    document_name: str = Field(serialization_alias="documentName")
    locator: str
    excerpt: str
    similarity: float = Field(ge=0, le=1)


class PrivateKnowledgeSearchOut(BaseModel):
    items: list[PrivateKnowledgeSearchResult]


class MessagePrivateKnowledgeSelectionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID | None
    name: str
    status: Literal["active", "deleted"]


class MessagePrivateKnowledgeCitationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_number: int = Field(serialization_alias="referenceNumber", ge=1, le=5)
    document_id: UUID | None = Field(default=None, serialization_alias="documentId")
    collection_name: str | None = Field(default=None, serialization_alias="collectionName")
    document_name: str = Field(serialization_alias="documentName")
    locator: str | None = None
    similarity: float = Field(ge=0, le=1)
    status: Literal["available", "deleted"]
