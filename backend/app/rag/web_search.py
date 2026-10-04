"""Opt-in search of generic medical topics; never send patient text."""

import hashlib
import ipaddress
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.privacy import redact_direct_identifiers
from app.models import KnowledgeChunk, KnowledgeDocument, KnowledgeSource
from app.rag.vectorizer import ControlledVectorizationError, vectorize_document

SOURCE_KEY = "web_search_prototype"
RECOGNIZED_DOMAINS = (
    ("nhc.gov.cn", "国家卫生健康委员会"),
    ("chinacdc.cn", "中国疾病预防控制中心"),
    ("nmpa.gov.cn", "国家药品监督管理局"),
)
BLOCKED_SUFFIXES = ("local", "internal", "test", "invalid", "example", "onion")
PUBLIC_HOST = re.compile(
    r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}"
)
TOPICS = (
    "甲状腺结节",
    "甲状腺功能亢进",
    "甲状腺功能减退",
    "甲状腺疾病",
    "鼻窦炎",
    "鼻炎",
    "胃食管反流",
    "胃炎",
    "胃溃疡",
    "胆囊炎",
    "胆结石",
    "脂肪肝",
    "肾结石",
    "尿路感染",
    "高血压",
    "糖尿病",
    "低血糖",
    "高血脂",
    "冠心病",
    "脑卒中",
    "哮喘",
    "肺炎",
    "支气管炎",
    "流感",
    "普通感冒",
    "新冠",
    "带状疱疹",
    "荨麻疹",
    "湿疹",
    "贫血",
    "痛风",
    "类风湿关节炎",
    "骨质疏松",
    "偏头痛",
    "颈椎病",
    "痔疮",
    "狂犬病",
    "乙肝",
    "幽门螺杆菌",
    "抑郁症",
    "焦虑症",
)

# A small, reviewed allowlist for overview questions. Only the canonical topic,
# never the patient's original text or symptoms, is sent to the search provider.
BROAD_TOPIC_ALIASES = {
    "甲状腺疾病": (
        "甲状腺相关疾病",
        "甲状腺疾病",
        "甲状腺有哪些病",
        "甲状腺有什么病",
        "甲状腺病有哪些",
        "常见甲状腺病",
    ),
}
BROAD_OVERVIEW_CUES = (
    "有哪些",
    "有什么病",
    "常见",
    "类型",
    "分类",
    "种类",
    "包括",
    "是什么",
    "介绍",
    "科普",
)
THYROID_COVERAGE_GROUPS = (
    ("甲状腺功能亢进", "甲亢"),
    ("甲状腺功能减退", "甲减"),
    ("甲状腺结节",),
    ("甲状腺炎", "桥本甲状腺炎"),
    ("甲状腺癌", "甲状腺肿瘤"),
)
BROAD_TOPIC_TERMS = {
    "甲状腺疾病": (
        "甲状腺疾病",
        "甲状腺病",
        "甲状腺功能亢进",
        "甲状腺功能减退",
        "甲亢",
        "甲减",
        "甲状腺结节",
        "甲状腺炎",
        "甲状腺癌",
        "甲状腺肿瘤",
    ),
}
BROAD_SEARCH_QUERIES = {
    "甲状腺疾病": "甲状腺 甲亢 甲减 结节",
}


@dataclass(frozen=True, slots=True)
class SearchHit:
    title: str
    url: str
    excerpt: str
    organization: str


class WebSearchError(RuntimeError):
    """Safe error code; never include provider payload or secrets."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def generic_topic(patient_text: str) -> str | None:
    """Select a fixed, non-personal topic only; no substring of user input is sent."""
    exact = next(
        (topic for topic in TOPICS if topic not in BROAD_TOPIC_ALIASES and topic in patient_text),
        None,
    )
    if exact:
        return exact
    normalized = re.sub(r"[\s？?。！!]+", "", patient_text)
    return next(
        (
            topic
            for topic, aliases in BROAD_TOPIC_ALIASES.items()
            if any(alias in normalized for alias in aliases)
            and (normalized in aliases or any(cue in normalized for cue in BROAD_OVERVIEW_CUES))
        ),
        None,
    )


UNKNOWN_TERM = re.compile(r"[\u4e00-\u9fff]{2,10}(?:综合征|注射液|胶囊|颗粒|片|病|炎|癌|症)")
QUOTED_TERM = re.compile(r"[“《]([\u4e00-\u9fff]{2,14})[”》]")
LEADING_TERM = re.compile(
    r"(?:^|[，。？！；\s])(?:什么是|了解|关于|得了|患有|确诊为|药名是|药品是|"
    r"想问|请问)\s*([\u4e00-\u9fff]{2,10}(?:综合征|注射液|胶囊|颗粒|片|病|炎|癌|症))"
    r"(?=是什么|有什么副作用|怎么治|怎么办|严重吗|能吃吗|[？，。！；]|$)"
)
TRAILING_TERM = re.compile(
    r"^([\u4e00-\u9fff]{2,14})(?:是什么|有哪些|有什么副作用|怎么治|怎么办|严重吗|能吃吗)"
)


def safe_search_topic(patient_text: str) -> str | None:
    """Extract one generic term; never pass the patient's sentence to a provider."""
    known = generic_topic(patient_text)
    if known:
        return known
    sanitized, _ = redact_direct_identifiers(patient_text)
    quoted = [match.group(1) for match in QUOTED_TERM.finditer(sanitized)]
    if quoted:
        candidates = quoted
    else:
        candidates = [match.group(1) for match in LEADING_TERM.finditer(sanitized)]
        if not candidates:
            candidates = [match.group(1) for match in TRAILING_TERM.finditer(sanitized)]
    if len(set(candidates)) != 1:
        return None
    term = candidates[0]
    personal_markers = ("姓名", "地址", "电话", "身份证", "我叫")
    if not allowed_search_topic(term) or any(word in term for word in personal_markers):
        return None
    return term


def allowed_search_topic(topic: str) -> bool:
    if topic in TOPICS:
        return True
    personal_markers = ("姓名", "地址", "电话", "身份证", "我叫")
    sanitized, redacted = redact_direct_identifiers(topic)
    return (
        not redacted
        and sanitized == topic
        and not any(word in topic for word in personal_markers)
        and bool(UNKNOWN_TERM.fullmatch(topic))
    )


def web_search_enabled() -> bool:
    return get_settings().web_search_enabled


def is_broad_topic(topic: str | None) -> bool:
    return topic in BROAD_TOPIC_TERMS


def topic_terms(topic: str) -> tuple[str, ...]:
    return BROAD_TOPIC_TERMS.get(topic, (topic,))


def topic_matches_text(topic: str, text: str) -> bool:
    return any(term in text for term in topic_terms(topic))


def topic_coverage_count(topic: str, texts: list[str]) -> int:
    """Conservative lexical coverage hint, not a medical completeness score."""
    if topic != "甲状腺疾病":
        return 0
    joined = " ".join(texts)
    return sum(any(alias in joined for alias in group) for group in THYROID_COVERAGE_GROUPS)


def broad_coverage_limited(topic: str | None, texts: list[str]) -> bool:
    return bool(topic and is_broad_topic(topic) and topic_coverage_count(topic, texts) < 2)


def web_hit_limit(topic: str) -> int:
    return 4 if is_broad_topic(topic) else 3


def trusted_organization(url: str) -> str | None:
    host = public_search_host(url)
    if host is None:
        return None
    for domain, name in RECOGNIZED_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return name
    return None


def public_search_host(url: str) -> str | None:
    """Reject local, malformed and official-lookalike URLs before using results."""
    if any(ord(char) < 32 for char in url) or len(url) > 1900:
        return None
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port:
            return None
        if not PUBLIC_HOST.fullmatch(host) or host.split(".")[-1] in BLOCKED_SUFFIXES:
            return None
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            return None
        for domain, _name in RECOGNIZED_DOMAINS:
            if domain in host and host != domain and not host.endswith("." + domain):
                return None
    except ValueError:
        return None
    return host


def source_organization(url: str) -> str | None:
    host = public_search_host(url)
    if host is None:
        return None
    return trusted_organization(url) or f"未核实网站（{host}）"


async def search_generic_topic(topic: str) -> list[SearchHit]:
    """Only validated generic terms may reach Tavily when explicitly enabled."""
    settings = get_settings()
    key = settings.tavily_api_key
    if not settings.web_search_enabled or not allowed_search_topic(topic):
        return []
    if (
        not key
        or not key.get_secret_value().strip()
        or settings.tavily_base_url.rstrip("/") != "https://api.tavily.com"
    ):
        raise WebSearchError("WEB_SEARCH_NOT_CONFIGURED")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=4.0)) as client:
            response = await client.post(
                "https://api.tavily.com/search",
                headers={"Authorization": f"Bearer {key.get_secret_value()}"},
                json={
                    "query": BROAD_SEARCH_QUERIES.get(topic, topic),
                    "search_depth": "basic",
                    "max_results": 8,
                    "language": "zh-cn",
                    "include_answer": False,
                    "include_raw_content": False,
                    "safe_search": True,
                },
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.TimeoutException as exc:
        raise WebSearchError("WEB_SEARCH_TIMEOUT") from exc
    except httpx.HTTPError as exc:
        raise WebSearchError("WEB_SEARCH_UNAVAILABLE") from exc
    except ValueError as exc:
        raise WebSearchError("WEB_SEARCH_INVALID_RESPONSE") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise WebSearchError("WEB_SEARCH_INVALID_RESPONSE")
    results = payload["results"]
    hits = []
    for item in results[:8]:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        title = item.get("title")
        content = item.get("content")
        if not all(isinstance(value, str) for value in (url, title, content)):
            continue
        # Broad queries often surface large official lists with only incidental
        # thyroid mentions. Require the disease topic in the page title as well.
        if is_broad_topic(topic) and not topic_matches_text(topic, title):
            continue
        organization = source_organization(url)
        searchable = re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", content)).strip()
        positions = (searchable.find(term) for term in topic_terms(topic))
        position = min((index for index in positions if index >= 0), default=-1)
        start = max(0, position - 120) if position >= 0 else 0
        excerpt = searchable[start : start + 480]
        if organization and topic_matches_text(topic, title + excerpt) and len(excerpt) >= 30:
            hits.append(SearchHit(title[:300], url[:1900], excerpt, organization))
    hits.sort(
        key=lambda hit: (
            trusted_organization(hit.url) is not None,
            topic_coverage_count(topic, [hit.title, hit.excerpt]),
        ),
        reverse=True,
    )
    diverse_hits = []
    seen_hosts = set()
    for hit in hits:
        host = public_search_host(hit.url)
        if host in seen_hosts:
            continue
        diverse_hits.append(hit)
        seen_hosts.add(host)
        if len(diverse_hits) >= web_hit_limit(topic):
            break
    return diverse_hits


async def save_search_prototypes(db: AsyncSession, topic: str, hits: list[SearchHit]) -> None:
    """Store short attributed snippets, never full fetched pages or approved material."""
    if not web_search_enabled() or not allowed_search_topic(topic):
        return
    if not hits:
        return
    source = await db.scalar(
        select(KnowledgeSource).where(KnowledgeSource.source_key == SOURCE_KEY)
    )
    if source is None:
        source = KnowledgeSource(
            source_key=SOURCE_KEY,
            priority=9,
            organization="联网搜索摘要（未经医学审核）",
            channel_name="Tavily 未审核搜索缓存",
            authority_level="web_search_prototype",
            jurisdiction="CN",
            language="zh-CN",
            entry_url="https://api.tavily.com",
            ingestion_status="prototype",
            automated_collection=True,
            source_metadata={
                "prototype_only": True,
                "medical_reviewed": False,
                "production_eligible": False,
            },
        )
        db.add(source)
        await db.flush()
    if source.ingestion_status != "prototype":
        return
    now = datetime.now(UTC)
    expires = (now + timedelta(days=30)).isoformat()
    for hit in hits:
        if source_organization(hit.url) != hit.organization or not topic_matches_text(
            topic, hit.title + hit.excerpt
        ):
            continue
        fingerprint = hashlib.sha256(hit.excerpt.encode("utf-8")).hexdigest()
        existing = await db.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.source_id == source.id,
                KnowledgeDocument.canonical_url == hit.url,
                KnowledgeDocument.content_hash == fingerprint,
            )
        )
        if existing:
            if existing.review_status != "prototype":
                continue
            existing.retrieved_at = now
            existing.document_metadata = {**existing.document_metadata, "web_expires_at": expires}
            try:
                await vectorize_document(db, existing.id)
            except ControlledVectorizationError:
                # A later search can retry indexing if the embedding service recovers.
                pass
            continue
        previous = await db.scalar(
            select(KnowledgeDocument)
            .where(
                KnowledgeDocument.source_id == source.id,
                KnowledgeDocument.canonical_url == hit.url,
                KnowledgeDocument.review_status == "prototype",
            )
            .order_by(KnowledgeDocument.created_at.desc())
            .limit(1)
        )
        if previous:
            previous.review_status = "superseded"
        doc = KnowledgeDocument(
            source_id=source.id,
            canonical_url=hit.url,
            title=hit.title,
            responsible_department=hit.organization,
            content_type="search_excerpt",
            language="zh-CN",
            jurisdiction="CN",
            retrieved_at=now,
            review_status="prototype",
            license_type="unverified_search_excerpt",
            license_notes="搜索摘要缓存；非网页全文，版权与医学内容均未经审核",
            content_hash=fingerprint,
            content_text=hit.excerpt,
            supersedes_document_id=previous.id if previous else None,
            document_metadata={
                "prototype_only": True,
                "medical_reviewed": False,
                "production_eligible": False,
                "web_expires_at": expires,
                "topics": [topic],
                "search_provider": "tavily",
            },
        )
        db.add(doc)
        await db.flush()
        db.add(
            KnowledgeChunk(
                document_id=doc.id,
                chunk_index=0,
                section_title="联网搜索摘要",
                section_path=["联网搜索摘要"],
                content=hit.excerpt,
                content_hash=fingerprint,
                chunk_metadata={"prototype_only": True, "medical_reviewed": False},
            )
        )
        await db.flush()
        try:
            await vectorize_document(db, doc.id)
        except ControlledVectorizationError:
            # The snippet remains an unindexed prototype and can be retried later.
            pass
