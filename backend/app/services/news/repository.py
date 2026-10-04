"""资讯快照的读写。**只碰数据库**，不发起任何网络请求。"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news import NEWS_ITEM_CATEGORIES, NewsItem, NewsSource
from app.services.news.feeds import FeedEntry, coerce_feed_timestamp
from app.services.news.validation import Rejection, validate_entry


@dataclass
class UpsertOutcome:
    inserted: int = 0
    refreshed: int = 0
    duplicate: int = 0
    rejected: list[Rejection] = field(default_factory=list)

    @property
    def accepted(self) -> int:
        return self.inserted + self.refreshed + self.duplicate


@dataclass
class NewsPage:
    rows: list[tuple[NewsItem, NewsSource]]
    total: int


async def enabled_sources(db: AsyncSession) -> list[NewsSource]:
    """只有显式启用（且经来源准入）的来源才会被刷新器与展示考虑。"""
    result = await db.execute(
        select(NewsSource).where(NewsSource.enabled.is_(True)).order_by(NewsSource.id)
    )
    return list(result.scalars())


async def _find_by_url(db: AsyncSession, *, source_id: str, url: str) -> NewsItem | None:
    result = await db.execute(
        select(NewsItem).where(
            NewsItem.source_id == source_id, NewsItem.canonical_url == url
        )
    )
    return result.scalar_one_or_none()


async def _find_by_fingerprint(
    db: AsyncSession, *, source_id: str, fingerprint: str
) -> NewsItem | None:
    result = await db.execute(
        select(NewsItem)
        .where(NewsItem.source_id == source_id, NewsItem.fingerprint == fingerprint)
        .order_by(NewsItem.first_seen_at)
        .limit(1)
    )
    return result.scalar_one_or_none()


def _category_for(source: NewsSource, entry: FeedEntry, allowed: list[str]) -> str | None:
    """分类解析：来源只有一个分类时用它；多个分类时必须由适配器给出明确分类。"""
    if len(allowed) == 1:
        return allowed[0]
    declared = (entry.category or "").strip()
    return declared if declared in allowed else None


async def upsert_entries(
    db: AsyncSession,
    *,
    source: NewsSource,
    entries: list[FeedEntry],
    now: datetime,
    display_days: int,
) -> UpsertOutcome:
    """把一轮抓到的条目并入快照：URL 去重、标题指纹处理同文多 URL、逐条受控拒收。"""
    outcome = UpsertOutcome()
    allowed = [c for c in (source.category_scope or []) if c in NEWS_ITEM_CATEGORIES]
    expires_at = now + timedelta(days=display_days)

    for entry in entries:
        category = _category_for(source, entry, allowed)
        if category is None:
            outcome.rejected.append(
                Rejection("CATEGORY_UNRESOLVED", "无法确定条目分类，未收录")
            )
            continue
        payload, rejection = validate_entry(
            source_id=source.id,
            category=category,
            allowed_categories=allowed,
            title=entry.title,
            url=entry.url,
            published_at=coerce_feed_timestamp(entry.published_raw),
            summary=entry.summary_raw,
            now=now,
        )
        if rejection is not None or payload is None:
            outcome.rejected.append(rejection or Rejection("INVALID_ENTRY", "条目校验未通过"))
            continue

        canonical_url = str(payload["canonical_url"])
        existing = await _find_by_url(db, source_id=source.id, url=canonical_url)
        if existing is not None:
            # 同一条新闻再次出现：刷新可见期；**不覆盖**已有摘要，也不编造时间。
            existing.last_seen_at = now
            existing.expires_at = expires_at
            if existing.published_at is None and payload["published_at"] is not None:
                existing.published_at = payload["published_at"]
            outcome.refreshed += 1
            continue

        twin = await _find_by_fingerprint(
            db, source_id=source.id, fingerprint=str(payload["fingerprint"])
        )
        if twin is not None:
            # 同文多 URL：只保留先到的那条，避免同一篇内容刷屏。
            twin.last_seen_at = now
            twin.expires_at = expires_at
            outcome.duplicate += 1
            continue

        db.add(
            NewsItem(
                source_id=source.id,
                category=str(payload["category"]),
                title=str(payload["title"]),
                summary=payload["summary"] if isinstance(payload["summary"], str) else None,
                canonical_url=canonical_url,
                published_at=(
                    payload["published_at"]
                    if isinstance(payload["published_at"], datetime)
                    else None
                ),
                first_seen_at=now,
                last_seen_at=now,
                expires_at=expires_at,
                fingerprint=str(payload["fingerprint"]),
                medical_reviewed=False,
            )
        )
        outcome.inserted += 1

    await db.flush()
    return outcome


async def read_items(
    db: AsyncSession,
    *,
    category: str,
    limit: int,
    offset: int,
    now: datetime,
) -> NewsPage:
    """读最近成功快照：只返回启用来源、且未过展示期的条目。"""
    query = (
        select(NewsItem, NewsSource)
        .join(NewsSource, NewsItem.source_id == NewsSource.id)
        .where(NewsSource.enabled.is_(True), NewsItem.expires_at > now)
    )
    if category != "all":
        query = query.where(NewsItem.category == category)

    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(
        query.order_by(
            NewsItem.published_at.desc().nullslast(),
            NewsItem.last_seen_at.desc(),
            NewsItem.id,
        )
        .limit(limit)
        .offset(offset)
    )
    return NewsPage(rows=[(item, source) for item, source in result.all()], total=int(total or 0))


async def latest_success_at(db: AsyncSession) -> datetime | None:
    """`asOf`：最近一次成功快照时间（不是接口调用时间）。"""
    return await db.scalar(
        select(func.max(NewsSource.last_success_at)).where(NewsSource.enabled.is_(True))
    )


async def source_statuses(db: AsyncSession, *, now: datetime) -> list[dict[str, object]]:
    """来源级状态（受控码）：ready / empty / failed / stale。"""
    sources = await enabled_sources(db)
    rows: list[dict[str, object]] = []
    for source in sources:
        count = await db.scalar(
            select(func.count())
            .select_from(NewsItem)
            .where(NewsItem.source_id == source.id, NewsItem.expires_at > now)
        )
        if source.last_error_code and not count:
            status = "failed"
        elif count:
            status = "ready"
        elif source.last_success_at is not None:
            status = "stale"
        else:
            status = "empty"
        rows.append(
            {
                "id": source.id,
                "name": source.name,
                "status": status,
                "lastSuccessAt": source.last_success_at,
                "lastErrorCode": source.last_error_code,
            }
        )
    return rows


async def withdraw_source_items(db: AsyncSession, *, source_id: str) -> int:
    """来源被撤回（停用/删除）时立即停止展示其条目。"""
    result = await db.execute(delete(NewsItem).where(NewsItem.source_id == source_id))
    return int(result.rowcount or 0)