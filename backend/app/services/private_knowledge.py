from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import decrypt_sensitive, encrypt_sensitive, sensitive_fingerprint
from app.models import (
    MessagePrivateKnowledgeCitation,
    MessagePrivateKnowledgeSelection,
    PrivateKnowledgeChunk,
    PrivateKnowledgeCollection,
    PrivateKnowledgeDocument,
    PrivateKnowledgeSearchTerm,
)
from app.rag.private_retrieval import (
    INDEX_VERSION,
    PrivateRetrievalItem,
    private_content_hmac,
    private_term_hmac,
    search_private_knowledge,
    tokenize_private_text,
)
from app.schemas.private_knowledge import (
    MessagePrivateKnowledgeCitationOut,
    MessagePrivateKnowledgeSelectionOut,
    PrivateKnowledgeCollectionList,
    PrivateKnowledgeCollectionOut,
    PrivateKnowledgeDocumentList,
    PrivateKnowledgeDocumentOut,
    PrivateKnowledgeSearchOut,
    PrivateKnowledgeSearchResult,
)
from app.services.document_extract import ExtractedDocument

MAX_COLLECTIONS = 20
MAX_DOCUMENTS_PER_COLLECTION = 100
PARSER_VERSION = "isolated-document-v1"


def _name_fingerprint(user_id: UUID, name: str) -> str:
    return sensitive_fingerprint(f"private-kb-name:{user_id}:{name.casefold()}")


def _collection_out(
    row: PrivateKnowledgeCollection, document_count: int
) -> PrivateKnowledgeCollectionOut:
    return PrivateKnowledgeCollectionOut(
        id=row.id,
        name=decrypt_sensitive(row.name_ciphertext),
        description=(
            decrypt_sensitive(row.description_ciphertext) if row.description_ciphertext else None
        ),
        status="active",
        document_count=document_count,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _owned_collection(
    db: AsyncSession, user_id: UUID, collection_id: UUID, *, lock: bool = False
) -> PrivateKnowledgeCollection:
    query = select(PrivateKnowledgeCollection).where(
        PrivateKnowledgeCollection.id == collection_id,
        PrivateKnowledgeCollection.user_id == user_id,
        PrivateKnowledgeCollection.status == "active",
    )
    if lock:
        query = query.with_for_update()
    row = await db.scalar(query)
    if row is None:
        raise AppError(404, "PRIVATE_KNOWLEDGE_COLLECTION_NOT_FOUND", "知识库不存在或无权访问")
    return row


async def create_collection(
    db: AsyncSession, user_id: UUID, name: str, description: str | None
) -> PrivateKnowledgeCollectionOut:
    count = await db.scalar(
        select(func.count())
        .select_from(PrivateKnowledgeCollection)
        .where(PrivateKnowledgeCollection.user_id == user_id)
    )
    if int(count or 0) >= MAX_COLLECTIONS:
        raise AppError(422, "PRIVATE_KNOWLEDGE_LIMIT_EXCEEDED", "每个账号最多创建 20 个知识库")
    row = PrivateKnowledgeCollection(
        user_id=user_id,
        name_ciphertext=encrypt_sensitive(name),
        name_fingerprint=_name_fingerprint(user_id, name),
        description_ciphertext=encrypt_sensitive(description) if description else None,
        status="active",
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise AppError(409, "PRIVATE_KNOWLEDGE_COLLECTION_EXISTS", "已有同名知识库") from exc
    result = _collection_out(row, 0)
    await db.commit()
    return result


async def list_collections(db: AsyncSession, user_id: UUID) -> PrivateKnowledgeCollectionList:
    counts = (
        select(
            PrivateKnowledgeDocument.collection_id,
            func.count(PrivateKnowledgeDocument.id).label("document_count"),
        )
        .where(PrivateKnowledgeDocument.user_id == user_id)
        .group_by(PrivateKnowledgeDocument.collection_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(PrivateKnowledgeCollection, func.coalesce(counts.c.document_count, 0))
            .outerjoin(counts, counts.c.collection_id == PrivateKnowledgeCollection.id)
            .where(
                PrivateKnowledgeCollection.user_id == user_id,
                PrivateKnowledgeCollection.status == "active",
            )
            .order_by(PrivateKnowledgeCollection.created_at, PrivateKnowledgeCollection.id)
        )
    ).all()
    return PrivateKnowledgeCollectionList(
        items=[_collection_out(row, int(count)) for row, count in rows]
    )


async def update_collection(
    db: AsyncSession,
    user_id: UUID,
    collection_id: UUID,
    name: str,
    description: str | None,
    *,
    update_description: bool = True,
) -> PrivateKnowledgeCollectionOut:
    row = await _owned_collection(db, user_id, collection_id, lock=True)
    row.name_ciphertext = encrypt_sensitive(name)
    row.name_fingerprint = _name_fingerprint(user_id, name)
    if update_description:
        row.description_ciphertext = encrypt_sensitive(description) if description else None
    row.updated_at = datetime.now(UTC)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise AppError(409, "PRIVATE_KNOWLEDGE_COLLECTION_EXISTS", "已有同名知识库") from exc
    count = await db.scalar(
        select(func.count())
        .select_from(PrivateKnowledgeDocument)
        .where(
            PrivateKnowledgeDocument.user_id == user_id,
            PrivateKnowledgeDocument.collection_id == collection_id,
        )
    )
    result = _collection_out(row, int(count or 0))
    await db.commit()
    return result


async def delete_collection(db: AsyncSession, user_id: UUID, collection_id: UUID) -> None:
    row = await _owned_collection(db, user_id, collection_id, lock=True)
    await db.delete(row)
    await db.commit()


async def _index_chunks(
    db: AsyncSession,
    *,
    user_id: UUID,
    document: PrivateKnowledgeDocument,
    extracted: ExtractedDocument,
) -> int:
    title_terms = tokenize_private_text(extracted.display_name)
    for item in extracted.chunks:
        chunk = PrivateKnowledgeChunk(
            user_id=user_id,
            document_id=document.id,
            position=item.position,
            locator=item.locator,
            content_ciphertext=encrypt_sensitive(item.text),
            content_hash_hmac=private_content_hmac(user_id, item.text),
            char_count=len(item.text),
        )
        db.add(chunk)
        await db.flush()
        terms = tokenize_private_text(item.text) | title_terms
        db.add_all(
            [
                PrivateKnowledgeSearchTerm(
                    user_id=user_id,
                    chunk_id=chunk.id,
                    term_hmac=private_term_hmac(user_id, term),
                )
                for term in sorted(terms)
            ]
        )
    await db.flush()
    return len(extracted.chunks)


async def create_document(
    db: AsyncSession,
    user_id: UUID,
    collection_id: UUID,
    extracted: ExtractedDocument,
) -> PrivateKnowledgeDocumentOut:
    await _owned_collection(db, user_id, collection_id, lock=True)
    count = await db.scalar(
        select(func.count())
        .select_from(PrivateKnowledgeDocument)
        .where(
            PrivateKnowledgeDocument.user_id == user_id,
            PrivateKnowledgeDocument.collection_id == collection_id,
        )
    )
    if int(count or 0) >= MAX_DOCUMENTS_PER_COLLECTION:
        raise AppError(422, "PRIVATE_KNOWLEDGE_LIMIT_EXCEEDED", "每个知识库最多保存 100 份文档")
    joined = "\n".join(chunk.text for chunk in extracted.chunks)
    row = PrivateKnowledgeDocument(
        user_id=user_id,
        collection_id=collection_id,
        display_name_ciphertext=encrypt_sensitive(extracted.display_name),
        kind=extracted.kind,
        byte_size=extracted.byte_size,
        page_count=extracted.page_count,
        char_count=extracted.char_count,
        content_hash_hmac=private_content_hmac(user_id, joined),
        status="indexing",
        parser_version=PARSER_VERSION,
        index_version=INDEX_VERSION,
    )
    db.add(row)
    try:
        await db.flush()
        chunk_count = await _index_chunks(db, user_id=user_id, document=row, extracted=extracted)
    except IntegrityError as exc:
        await db.rollback()
        raise AppError(
            409, "PRIVATE_KNOWLEDGE_DOCUMENT_EXISTS", "该知识库中已有相同内容的文档"
        ) from exc
    row.status = "ready"
    row.updated_at = datetime.now(UTC)
    await db.flush()
    result = _document_out(row, chunk_count)
    await db.commit()
    return result


def _document_out(row: PrivateKnowledgeDocument, chunk_count: int) -> PrivateKnowledgeDocumentOut:
    return PrivateKnowledgeDocumentOut(
        id=row.id,
        collection_id=row.collection_id,
        display_name=decrypt_sensitive(row.display_name_ciphertext),
        kind=row.kind,
        byte_size=row.byte_size,
        page_count=row.page_count,
        char_count=row.char_count,
        chunk_count=chunk_count,
        status=row.status,
        error_code=row.error_code,
        parser_version=row.parser_version,
        index_version=row.index_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def list_documents(
    db: AsyncSession, user_id: UUID, collection_id: UUID
) -> PrivateKnowledgeDocumentList:
    await _owned_collection(db, user_id, collection_id)
    counts = (
        select(
            PrivateKnowledgeChunk.document_id,
            func.count(PrivateKnowledgeChunk.id).label("chunk_count"),
        )
        .where(PrivateKnowledgeChunk.user_id == user_id)
        .group_by(PrivateKnowledgeChunk.document_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(PrivateKnowledgeDocument, func.coalesce(counts.c.chunk_count, 0))
            .outerjoin(counts, counts.c.document_id == PrivateKnowledgeDocument.id)
            .where(
                PrivateKnowledgeDocument.user_id == user_id,
                PrivateKnowledgeDocument.collection_id == collection_id,
            )
            .order_by(PrivateKnowledgeDocument.created_at, PrivateKnowledgeDocument.id)
        )
    ).all()
    return PrivateKnowledgeDocumentList(
        items=[_document_out(row, int(count)) for row, count in rows]
    )


async def get_document(
    db: AsyncSession, user_id: UUID, document_id: UUID
) -> PrivateKnowledgeDocumentOut:
    row = await db.scalar(
        select(PrivateKnowledgeDocument).where(
            PrivateKnowledgeDocument.id == document_id,
            PrivateKnowledgeDocument.user_id == user_id,
        )
    )
    if row is None:
        raise AppError(404, "PRIVATE_KNOWLEDGE_DOCUMENT_NOT_FOUND", "文档不存在或无权访问")
    count = await db.scalar(
        select(func.count())
        .select_from(PrivateKnowledgeChunk)
        .where(
            PrivateKnowledgeChunk.user_id == user_id,
            PrivateKnowledgeChunk.document_id == document_id,
        )
    )
    return _document_out(row, int(count or 0))


async def delete_document(db: AsyncSession, user_id: UUID, document_id: UUID) -> None:
    row = await db.scalar(
        select(PrivateKnowledgeDocument)
        .where(
            PrivateKnowledgeDocument.id == document_id,
            PrivateKnowledgeDocument.user_id == user_id,
        )
        .with_for_update()
    )
    if row is None:
        raise AppError(404, "PRIVATE_KNOWLEDGE_DOCUMENT_NOT_FOUND", "文档不存在或无权访问")
    await db.delete(row)
    await db.commit()


async def retry_document(
    db: AsyncSession, user_id: UUID, document_id: UUID
) -> PrivateKnowledgeDocumentOut:
    row = await db.scalar(
        select(PrivateKnowledgeDocument)
        .where(
            PrivateKnowledgeDocument.id == document_id,
            PrivateKnowledgeDocument.user_id == user_id,
        )
        .with_for_update()
    )
    if row is None:
        raise AppError(404, "PRIVATE_KNOWLEDGE_DOCUMENT_NOT_FOUND", "文档不存在或无权访问")
    chunks = (
        await db.scalars(
            select(PrivateKnowledgeChunk)
            .where(
                PrivateKnowledgeChunk.user_id == user_id,
                PrivateKnowledgeChunk.document_id == document_id,
            )
            .order_by(PrivateKnowledgeChunk.position)
        )
    ).all()
    if not chunks:
        raise AppError(409, "PRIVATE_KNOWLEDGE_INDEX_NOT_READY", "原件未保存，无法重新解析该文档")
    await db.execute(
        delete(PrivateKnowledgeSearchTerm).where(
            PrivateKnowledgeSearchTerm.user_id == user_id,
            PrivateKnowledgeSearchTerm.chunk_id.in_([chunk.id for chunk in chunks]),
        )
    )
    title = decrypt_sensitive(row.display_name_ciphertext)
    for chunk in chunks:
        text = decrypt_sensitive(chunk.content_ciphertext)
        terms = tokenize_private_text(text) | tokenize_private_text(title)
        db.add_all(
            [
                PrivateKnowledgeSearchTerm(
                    user_id=user_id,
                    chunk_id=chunk.id,
                    term_hmac=private_term_hmac(user_id, term),
                )
                for term in sorted(terms)
            ]
        )
    row.status = "ready"
    row.error_code = None
    row.index_version = INDEX_VERSION
    row.updated_at = datetime.now(UTC)
    await db.commit()
    return _document_out(row, len(chunks))


async def validate_collection_ids(
    db: AsyncSession, user_id: UUID, collection_ids: list[UUID]
) -> list[PrivateKnowledgeCollection]:
    if len(collection_ids) > 3 or len(set(collection_ids)) != len(collection_ids):
        raise AppError(
            422,
            "PRIVATE_KNOWLEDGE_SELECTION_INVALID",
            "每次最多选择 3 个不同的知识库",
        )
    if not collection_ids:
        return []
    rows = (
        await db.scalars(
            select(PrivateKnowledgeCollection).where(
                PrivateKnowledgeCollection.id.in_(collection_ids),
                PrivateKnowledgeCollection.user_id == user_id,
                PrivateKnowledgeCollection.status == "active",
            )
        )
    ).all()
    by_id = {row.id: row for row in rows}
    if set(by_id) != set(collection_ids):
        raise AppError(
            422,
            "PRIVATE_KNOWLEDGE_SELECTION_INVALID",
            "所选知识库不存在或无权访问",
        )
    return [by_id[item] for item in collection_ids]


async def bind_message_selections(
    db: AsyncSession,
    *,
    user_id: UUID,
    message_id: UUID,
    collection_ids: list[UUID],
) -> list[MessagePrivateKnowledgeSelectionOut]:
    rows = await validate_collection_ids(db, user_id, collection_ids)
    db.add_all(
        [
            MessagePrivateKnowledgeSelection(
                message_id=message_id,
                collection_id=row.id,
                position=position,
            )
            for position, row in enumerate(rows)
        ]
    )
    if rows:
        await db.flush()
    return [
        MessagePrivateKnowledgeSelectionOut(
            id=row.id,
            name=decrypt_sensitive(row.name_ciphertext),
            status="active",
        )
        for row in rows
    ]


async def collection_ids_for_message(db: AsyncSession, message_id: UUID) -> list[UUID]:
    return list(
        await db.scalars(
            select(MessagePrivateKnowledgeSelection.collection_id)
            .where(
                MessagePrivateKnowledgeSelection.message_id == message_id,
                MessagePrivateKnowledgeSelection.collection_id.is_not(None),
            )
            .order_by(MessagePrivateKnowledgeSelection.position)
        )
    )


async def message_selections(
    db: AsyncSession, message_ids: list[UUID]
) -> dict[UUID, list[MessagePrivateKnowledgeSelectionOut]]:
    if not message_ids:
        return {}
    rows = (
        await db.execute(
            select(MessagePrivateKnowledgeSelection, PrivateKnowledgeCollection)
            .outerjoin(
                PrivateKnowledgeCollection,
                MessagePrivateKnowledgeSelection.collection_id == PrivateKnowledgeCollection.id,
            )
            .where(MessagePrivateKnowledgeSelection.message_id.in_(message_ids))
            .order_by(
                MessagePrivateKnowledgeSelection.message_id,
                MessagePrivateKnowledgeSelection.position,
            )
        )
    ).all()
    result: defaultdict[UUID, list[MessagePrivateKnowledgeSelectionOut]] = defaultdict(list)
    for link, collection in rows:
        result[link.message_id].append(
            MessagePrivateKnowledgeSelectionOut(
                id=collection.id if collection else None,
                name=(
                    decrypt_sensitive(collection.name_ciphertext) if collection else "知识库已删除"
                ),
                status="active" if collection else "deleted",
            )
        )
    return dict(result)


async def search(
    db: AsyncSession,
    *,
    user_id: UUID,
    collection_ids: list[UUID],
    query: str,
    limit: int = 5,
) -> PrivateKnowledgeSearchOut:
    await validate_collection_ids(db, user_id, collection_ids)
    items = await search_private_knowledge(
        db,
        user_id=user_id,
        collection_ids=collection_ids,
        query=query,
        limit=limit,
    )
    return PrivateKnowledgeSearchOut(
        items=[
            PrivateKnowledgeSearchResult(
                reference_number=index,
                collection_id=item.collection_id,
                collection_name=item.collection_name,
                document_id=item.document_id,
                document_name=item.document_name,
                locator=item.locator,
                excerpt=item.content[:500] + ("…" if len(item.content) > 500 else ""),
                similarity=item.similarity,
            )
            for index, item in enumerate(items, start=1)
        ]
    )


async def selected_retrieval(
    db: AsyncSession,
    *,
    user_id: UUID,
    message_id: UUID,
    query: str,
) -> list[PrivateRetrievalItem]:
    collection_ids = await collection_ids_for_message(db, message_id)
    if not collection_ids:
        return []
    return await search_private_knowledge(
        db,
        user_id=user_id,
        collection_ids=collection_ids,
        query=query,
        limit=5,
    )


async def save_message_citations(
    db: AsyncSession,
    *,
    message_id: UUID,
    citations: list[dict[str, object]],
) -> None:
    db.add_all(
        [
            MessagePrivateKnowledgeCitation(
                message_id=message_id,
                document_id=item["document_id"],
                reference_number=item["reference_number"],
                locator=item["locator"],
                similarity=item["similarity"],
            )
            for item in citations
        ]
    )
    if citations:
        await db.flush()


async def message_citations(
    db: AsyncSession, message_ids: list[UUID]
) -> dict[UUID, list[MessagePrivateKnowledgeCitationOut]]:
    if not message_ids:
        return {}
    rows = (
        await db.execute(
            select(
                MessagePrivateKnowledgeCitation,
                PrivateKnowledgeDocument,
                PrivateKnowledgeCollection,
            )
            .outerjoin(
                PrivateKnowledgeDocument,
                MessagePrivateKnowledgeCitation.document_id == PrivateKnowledgeDocument.id,
            )
            .outerjoin(
                PrivateKnowledgeCollection,
                PrivateKnowledgeDocument.collection_id == PrivateKnowledgeCollection.id,
            )
            .where(MessagePrivateKnowledgeCitation.message_id.in_(message_ids))
            .order_by(
                MessagePrivateKnowledgeCitation.message_id,
                MessagePrivateKnowledgeCitation.reference_number,
            )
        )
    ).all()
    result: defaultdict[UUID, list[MessagePrivateKnowledgeCitationOut]] = defaultdict(list)
    for citation, document, collection in rows:
        available = document is not None and collection is not None
        result[citation.message_id].append(
            MessagePrivateKnowledgeCitationOut(
                reference_number=citation.reference_number,
                document_id=document.id if available else None,
                collection_name=(
                    decrypt_sensitive(collection.name_ciphertext) if available else None
                ),
                document_name=(
                    decrypt_sensitive(document.display_name_ciphertext)
                    if available
                    else "私人资料已删除"
                ),
                locator=citation.locator if available else None,
                similarity=citation.similarity,
                status="available" if available else "deleted",
            )
        )
    return dict(result)
