"""概念与别名的登记（G1）。

登记入口只有受控 CLI：概念、别名都必须来自人工维护或审核资料，**不接受用户输入或模型的
自由写入**（plan 第 5.1 节）。规范名可以改，但 ID 不变——历史 claim 与证据都挂在 ID 上。
停用的概念不会因为再次登记而复活，避免把已下线的词悄悄拉回线上。
"""

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_graph import (
    ConceptType,
    GraphConcept,
    GraphConceptAlias,
    GraphConceptStatus,
)
from app.schemas.knowledge_graph import GraphConceptSeedFile
from app.services.knowledge_graph_vocabulary import normalize_concept_name


class KnowledgeGraphRegistryError(ValueError):
    """登记失败：概念已停用、名称为空等。"""


@dataclass(slots=True)
class ConceptRegistrationResult:
    concept_id: UUID
    concept_type: str
    canonical_name: str
    created: bool
    renamed: bool
    aliases_added: list[str] = field(default_factory=list)
    aliases_skipped: list[str] = field(default_factory=list)


async def register_concept(
    db: AsyncSession,
    *,
    concept_type: ConceptType | str,
    canonical_name: str,
    aliases: tuple[str, ...] | list[str] = (),
) -> ConceptRegistrationResult:
    resolved_type = ConceptType(concept_type)
    resolved_name = canonical_name.strip()
    normalized = normalize_concept_name(resolved_name)
    concept = await db.scalar(
        select(GraphConcept).where(
            GraphConcept.concept_type == resolved_type,
            GraphConcept.normalized_name == normalized,
        )
    )
    renamed = False
    if concept is None:
        await _reject_alias_collision(db, normalized)
        concept = GraphConcept(
            concept_type=resolved_type,
            canonical_name=resolved_name,
            normalized_name=normalized,
            status=GraphConceptStatus.ACTIVE,
            version=1,
        )
        db.add(concept)
        await db.flush()
        created = True
    else:
        created = False
        if concept.status != GraphConceptStatus.ACTIVE:
            raise KnowledgeGraphRegistryError(
                f"概念「{concept.canonical_name}」已停用；要恢复必须先人工确认，登记不会自动复活"
            )
        # 已存在的概念**只补别名**：规范名改动一律走 rename_concept，避免因为空格/全角等
        # 书写差异就悄悄改掉线上名字并涨版本号。
        renamed = False

    result = await _add_aliases(db, concept, aliases)
    result.created = created
    result.renamed = renamed
    return result


async def seed_concepts(
    db: AsyncSession, seed: GraphConceptSeedFile
) -> list[ConceptRegistrationResult]:
    """批量登记（幂等：同一份文件重复执行不会产生重复概念或别名）。"""

    results: list[ConceptRegistrationResult] = []
    for item in seed.concepts:
        results.append(
            await register_concept(
                db,
                concept_type=item.concept_type,
                canonical_name=item.canonical_name,
                aliases=item.aliases,
            )
        )
    return results


async def rename_concept(
    db: AsyncSession, concept_id: UUID, *, canonical_name: str
) -> ConceptRegistrationResult:
    """改规范名：**ID 不变**，旧名自动留成别名。

    按名字登记无法表达改名（新名字必然找不到旧行，会被当成新概念），所以改名必须由 ID 指定。
    旧名留成别名是必须的：线上正文里写的还是旧名，不留别名就会突然匹配不到。
    """

    concept = await db.get(GraphConcept, concept_id)
    if concept is None:
        raise KnowledgeGraphRegistryError(f"概念不存在：{concept_id}")
    if concept.status != GraphConceptStatus.ACTIVE:
        raise KnowledgeGraphRegistryError(f"概念「{concept.canonical_name}」已停用，不能改名")
    resolved_name = canonical_name.strip()
    normalized = normalize_concept_name(resolved_name)
    old_normalized = concept.normalized_name
    if normalized == old_normalized:
        return ConceptRegistrationResult(
            concept_id=concept.id,
            concept_type=concept.concept_type,
            canonical_name=concept.canonical_name,
            created=False,
            renamed=False,
        )
    taken = await db.scalar(
        select(GraphConcept).where(
            GraphConcept.concept_type == concept.concept_type,
            GraphConcept.normalized_name == normalized,
            GraphConcept.id != concept.id,
        )
    )
    if taken is not None:
        raise KnowledgeGraphRegistryError(
            f"同类型下已存在规范名为「{taken.canonical_name}」的概念，改名会撞车"
        )
    await _reject_alias_collision(db, normalized, allowed_concept_id=concept.id)
    # 顺序很关键：先把新名落成规范名，再把**旧名**登记成别名。反过来做的话，旧名会因为
    # 「与当前规范名相同」被当成重复别名跳过，改完名正文里的旧名就再也匹配不上了。
    previous_name = concept.canonical_name
    concept.canonical_name = resolved_name
    concept.normalized_name = normalized
    concept.version += 1
    await db.flush()
    result = await _add_aliases(db, concept, (previous_name,))
    result.renamed = True
    from sqlalchemy import func

    from app.models.knowledge_graph import GraphClaim, GraphClaimStatus
    from app.services.knowledge_graph_publication import enqueue_snapshot_rebuild

    live_uses = await db.scalar(
        select(func.count()).select_from(GraphClaim).where(
            GraphClaim.status == GraphClaimStatus.PUBLISHED,
            (GraphClaim.subject_concept_id == concept.id)
            | (GraphClaim.object_concept_id == concept.id),
        )
    )
    if live_uses:
        await enqueue_snapshot_rebuild(db, actor="concept-rename")
    return result


async def _add_aliases(
    db: AsyncSession, concept: GraphConcept, aliases: tuple[str, ...] | list[str]
) -> ConceptRegistrationResult:
    existing_alias_texts = {
        alias.normalized_text
        for alias in (
            await db.scalars(
                select(GraphConceptAlias).where(GraphConceptAlias.concept_id == concept.id)
            )
        ).all()
    }
    result = ConceptRegistrationResult(
        concept_id=concept.id,
        concept_type=concept.concept_type,
        canonical_name=concept.canonical_name,
        created=False,
        renamed=False,
    )
    for alias in aliases:
        text = alias.strip()
        if not text:
            continue
        normalized_alias = normalize_concept_name(text)
        if normalized_alias == concept.normalized_name or normalized_alias in existing_alias_texts:
            result.aliases_skipped.append(text)
            continue
        db.add(
            GraphConceptAlias(
                concept_id=concept.id,
                text=text,
                normalized_text=normalized_alias,
                status=GraphConceptStatus.ACTIVE,
            )
        )
        existing_alias_texts.add(normalized_alias)
        result.aliases_added.append(text)
    await db.flush()
    return result


async def _reject_alias_collision(
    db: AsyncSession, normalized: str, *, allowed_concept_id: UUID | None = None
) -> None:
    """要登记的规范名已经是别人的别名时直接报错，不要静默造出第二个概念。"""

    query = select(GraphConceptAlias).where(GraphConceptAlias.normalized_text == normalized)
    if allowed_concept_id is not None:
        query = query.where(GraphConceptAlias.concept_id != allowed_concept_id)
    alias = await db.scalar(query)
    if alias is None:
        return
    owner = await db.get(GraphConcept, alias.concept_id)
    owner_name = owner.canonical_name if owner else "（已删除）"
    raise KnowledgeGraphRegistryError(
        f"「{normalized}」已经是概念「{owner_name}」的别名；"
        "要改概念名请用 rename-concept（会保留 ID），要新增别名请登记到同一个概念上"
    )
