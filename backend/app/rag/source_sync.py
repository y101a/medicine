import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeSource

DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "medical_source_registry.json"
)


class SourceRegistryError(ValueError):
    """Raised when the reviewed source registry is malformed or inconsistent."""


@dataclass(frozen=True, slots=True)
class SourceSyncResult:
    approved_requested: int
    created: int
    updated: int
    demoted: int
    source_keys: tuple[str, ...]


def load_source_registry(path: Path | None = None) -> dict[str, Any]:
    registry_path = (path or DEFAULT_REGISTRY_PATH).resolve()
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceRegistryError("无法读取或解析医学来源注册表") from exc
    if not isinstance(registry, dict):
        raise SourceRegistryError("医学来源注册表根节点必须是对象")
    return registry


def _approved_entries(registry: dict[str, Any]) -> list[dict[str, Any]]:
    policy = registry.get("policy")
    sources = registry.get("sources")
    if not isinstance(policy, dict) or not isinstance(sources, list):
        raise SourceRegistryError("医学来源注册表缺少 policy 或 sources")
    approved = policy.get("approved_for_ingestion")
    if not isinstance(approved, list) or not all(isinstance(item, str) for item in approved):
        raise SourceRegistryError("approved_for_ingestion 必须是来源 ID 字符串数组")
    if len(approved) != len(set(approved)):
        raise SourceRegistryError("approved_for_ingestion 中存在重复来源 ID")

    entries: dict[str, dict[str, Any]] = {}
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("id"), str):
            raise SourceRegistryError("每个来源必须包含字符串类型的 id")
        source_id = source["id"]
        if source_id in entries:
            raise SourceRegistryError(f"来源 ID 重复：{source_id}")
        entries[source_id] = source
    unknown = set(approved) - set(entries)
    if unknown:
        raise SourceRegistryError(f"批准列表包含未知来源：{', '.join(sorted(unknown))}")
    return [entries[source_id] for source_id in approved]


def _source_values(entry: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    required = (
        "id",
        "priority",
        "organization",
        "channel_name",
        "authority_level",
        "jurisdiction",
        "language",
        "entry_url",
    )
    missing = [key for key in required if not entry.get(key)]
    if missing:
        raise SourceRegistryError(
            f"来源 {entry.get('id', '<unknown>')} 缺少字段：{', '.join(missing)}"
        )
    return {
        "source_key": entry["id"],
        "priority": entry["priority"],
        "organization": entry["organization"],
        "channel_name": entry["channel_name"],
        "authority_level": entry["authority_level"],
        "jurisdiction": entry["jurisdiction"],
        "language": entry["language"],
        "entry_url": entry["entry_url"],
        "legal_notice_url": entry.get("legal_notice_url"),
        "ingestion_status": "approved",
        # Approval permits controlled local import, never unattended crawling.
        "automated_collection": False,
        "source_metadata": {
            "registry_managed": True,
            "registry_reviewed_at": registry.get("reviewed_at"),
            "registry_ingestion_status": entry.get("ingestion_status"),
            "content_scope": entry.get("content_scope", []),
            "rag_role": entry.get("rag_role"),
            "notes": entry.get("notes"),
        },
    }


async def sync_approved_sources(
    db: AsyncSession, registry_path: Path | None = None
) -> SourceSyncResult:
    registry = load_source_registry(registry_path)
    entries = _approved_entries(registry)
    approved_keys = {entry["id"] for entry in entries}
    existing_rows = list(await db.scalars(select(KnowledgeSource)))
    existing_by_key = {row.source_key: row for row in existing_rows}

    created = 0
    updated = 0
    demoted = 0
    for row in existing_rows:
        managed = bool((row.source_metadata or {}).get("registry_managed"))
        if managed and row.source_key not in approved_keys and row.ingestion_status == "approved":
            row.ingestion_status = "candidate"
            row.automated_collection = False
            demoted += 1

    for entry in entries:
        values = _source_values(entry, registry)
        row = existing_by_key.get(entry["id"])
        if row is None:
            db.add(KnowledgeSource(**values))
            created += 1
            continue
        for key, value in values.items():
            setattr(row, key, value)
        updated += 1

    await db.flush()
    return SourceSyncResult(
        approved_requested=len(entries),
        created=created,
        updated=updated,
        demoted=demoted,
        source_keys=tuple(entry["id"] for entry in entries),
    )
