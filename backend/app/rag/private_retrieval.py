"""Privacy-first retrieval over encrypted user-owned knowledge chunks.

Only HMAC tokens are stored. Candidate text is decrypted in process for bounded
reranking; raw queries, terms and document text are never logged.
"""

import re
import unicodedata
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.privacy import redact_direct_identifiers
from app.core.security import decrypt_sensitive, sensitive_fingerprint
from app.models import (
    PrivateKnowledgeChunk,
    PrivateKnowledgeCollection,
    PrivateKnowledgeDocument,
    PrivateKnowledgeSearchTerm,
)

INDEX_VERSION = "private-keyword-v1"
MIN_RELEVANCE = 0.2
MAX_CANDIDATES = 40


@dataclass(frozen=True)
class PrivateRetrievalItem:
    collection_id: UUID
    collection_name: str
    document_id: UUID
    document_name: str
    chunk_id: UUID
    locator: str
    content: str
    similarity: float


def tokenize_private_text(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    tokens = set(re.findall(r"[a-z0-9]+(?:[._/-][a-z0-9]+)*", normalized))
    for sequence in re.findall(r"[\u4e00-\u9fff]{2,}", normalized):
        if len(sequence) <= 12:
            tokens.add(sequence)
        tokens.update(sequence[index : index + 2] for index in range(len(sequence) - 1))
        tokens.update(sequence[index : index + 3] for index in range(len(sequence) - 2))
    return {token for token in tokens if 1 < len(token) <= 64}


def private_term_hmac(user_id: UUID, term: str) -> str:
    return sensitive_fingerprint(f"private-kb-term:{user_id}:{term}")


def private_content_hmac(user_id: UUID, value: str) -> str:
    return sensitive_fingerprint(f"private-kb-content:{user_id}:{value}")


def _score(query: str, query_terms: set[str], content: str, document_name: str) -> float:
    candidate = f"{document_name}\n{content}"
    candidate_terms = tokenize_private_text(candidate)
    if not query_terms:
        return 0.0
    # A natural-language question contains many filler n-grams (for example
    # “是多少/怎么理解”). Capping the denominator keeps an exact medical-term
    # match from being diluted while a zero-overlap query still scores zero.
    overlap = len(query_terms & candidate_terms) / max(1, min(len(query_terms), 5))
    normalized_query = unicodedata.normalize("NFKC", query).casefold().strip()
    phrase_bonus = (
        0.25 if len(normalized_query) >= 2 and normalized_query in candidate.casefold() else 0
    )
    return min(1.0, overlap * 0.85 + phrase_bonus)


async def search_private_knowledge(
    db: AsyncSession,
    *,
    user_id: UUID,
    collection_ids: list[UUID],
    query: str,
    limit: int = 5,
) -> list[PrivateRetrievalItem]:
    if not collection_ids or limit < 1:
        return []
    query_terms = tokenize_private_text(query)
    if not query_terms:
        return []
    hashes = [private_term_hmac(user_id, term) for term in query_terms]
    candidate_rows = (
        await db.execute(
            select(
                PrivateKnowledgeSearchTerm.chunk_id,
                func.count(PrivateKnowledgeSearchTerm.id).label("matches"),
            )
            .join(
                PrivateKnowledgeChunk,
                PrivateKnowledgeChunk.id == PrivateKnowledgeSearchTerm.chunk_id,
            )
            .join(
                PrivateKnowledgeDocument,
                PrivateKnowledgeDocument.id == PrivateKnowledgeChunk.document_id,
            )
            .where(
                PrivateKnowledgeSearchTerm.user_id == user_id,
                PrivateKnowledgeSearchTerm.term_hmac.in_(hashes),
                PrivateKnowledgeChunk.user_id == user_id,
                PrivateKnowledgeDocument.user_id == user_id,
                PrivateKnowledgeDocument.collection_id.in_(collection_ids),
                PrivateKnowledgeDocument.status == "ready",
            )
            .group_by(PrivateKnowledgeSearchTerm.chunk_id)
            .order_by(func.count(PrivateKnowledgeSearchTerm.id).desc())
            .limit(MAX_CANDIDATES)
        )
    ).all()
    if not candidate_rows:
        return []
    chunk_ids = [row.chunk_id for row in candidate_rows]
    rows = (
        await db.execute(
            select(PrivateKnowledgeChunk, PrivateKnowledgeDocument, PrivateKnowledgeCollection)
            .join(
                PrivateKnowledgeDocument,
                PrivateKnowledgeDocument.id == PrivateKnowledgeChunk.document_id,
            )
            .join(
                PrivateKnowledgeCollection,
                PrivateKnowledgeCollection.id == PrivateKnowledgeDocument.collection_id,
            )
            .where(
                PrivateKnowledgeChunk.id.in_(chunk_ids),
                PrivateKnowledgeChunk.user_id == user_id,
                PrivateKnowledgeDocument.user_id == user_id,
                PrivateKnowledgeCollection.user_id == user_id,
                PrivateKnowledgeCollection.id.in_(collection_ids),
                PrivateKnowledgeCollection.status == "active",
            )
        )
    ).all()
    ranked: list[PrivateRetrievalItem] = []
    for chunk, document, collection in rows:
        content = decrypt_sensitive(chunk.content_ciphertext)
        document_name = decrypt_sensitive(document.display_name_ciphertext)
        score = _score(query, query_terms, content, document_name)
        if score < MIN_RELEVANCE:
            continue
        redacted, _ = redact_direct_identifiers(content)
        ranked.append(
            PrivateRetrievalItem(
                collection_id=collection.id,
                collection_name=decrypt_sensitive(collection.name_ciphertext),
                document_id=document.id,
                document_name=document_name,
                chunk_id=chunk.id,
                locator=chunk.locator,
                content=redacted,
                similarity=score,
            )
        )
    ranked.sort(key=lambda item: (-item.similarity, item.document_name, item.locator))
    selected: list[PrivateRetrievalItem] = []
    documents: set[UUID] = set()
    for item in ranked:
        if item.document_id not in documents and len(documents) >= 2:
            continue
        selected.append(item)
        documents.add(item.document_id)
        if len(selected) >= min(limit, 5):
            break
    return selected
