import importlib
import os
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from docx import Document
from pptx import Presentation
from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import create_access_token
from app.models import (
    GeneratedDocument,
    GeneratedDocumentDeletionJob,
    GeneratedDocumentFile,
)
from app.rag.retrieval import RetrievalCitation, RetrievalResult
from app.services import document_generations as generation_service
from app.services.auth import ACCESS_COOKIE
from app.services.document_generation_content import DocumentContentPlan
from app.services.document_generation_intent import medical_document_generation_request
from app.services.document_renderers import render_docx, render_pptx
from app.services.generated_document_deletion import (
    process_document_deletion_jobs,
    reconcile_orphaned_generated_documents,
)
from app.services.generated_document_validation import validate_generated_document


def _plan() -> DocumentContentPlan:
    return DocumentContentPlan.model_validate(
        {
            "title": "高血压预防科普",
            "audience": "普通成年人",
            "summary": "高血压预防需要长期关注生活方式、规范测量血压并按需接受医疗评估。",
            "sections": [
                {
                    "heading": "认识高血压",
                    "paragraphs": ["血压水平需要结合规范测量结果进行判断。"],
                    "bullets": [],
                    "sourceIds": [1],
                },
                {
                    "heading": "日常预防",
                    "paragraphs": [],
                    "bullets": ["保持规律运动和合理饮食。", "按建议记录血压变化。"],
                    "sourceIds": [1],
                },
            ],
            "warningSigns": [
                {"text": "出现胸痛、呼吸困难等表现时应及时就医。", "sourceIds": [1]}
            ],
        }
    )


def _citation() -> RetrievalCitation:
    return RetrievalCitation(
        chunk_id=uuid4(),
        document_id=uuid4(),
        source_key="developer_prototype_knowledge",
        organization="项目开发者",
        title="高血压原型资料",
        canonical_url="https://prototype.invalid/medical-knowledge/hypertension",
        section_title="预防",
        version_label="test",
        published_at=None,
        content="高血压预防包括合理饮食、规律运动和规范测量。",
        similarity=0.9,
        trust_level="prototype",
    )


@pytest.mark.parametrize(
    ("content", "formats"),
    [
        ("帮我生成一份高血压预防 PPT", ("pptx",)),
        ("制作胃食管反流 Word 科普文档", ("docx",)),
        ("把哮喘预防做成 PPT 和 Word", ("docx", "pptx")),
    ],
)
def test_document_generation_intent_requires_explicit_format(content, formats):
    result = medical_document_generation_request(content)
    assert result is not None
    assert result.formats == formats


@pytest.mark.parametrize(
    "content",
    [
        "你能生成 PPT 吗？",
        "不要生成高血压 Word 文档",
        "生成一份年度销售 PPT",
        "生成一份人体结构科普资料",
        "介绍一下人体结构",
    ],
)
def test_non_document_generation_intent(content):
    assert medical_document_generation_request(content) is None


def test_renderers_create_safe_reopenable_office_files():
    sources = [
        {
            "referenceNumber": 1,
            "organization": "项目开发者",
            "title": "高血压原型资料",
            "canonicalUrl": "https://prototype.invalid/medical-knowledge/hypertension",
        }
    ]
    docx = render_docx(_plan(), sources)
    pptx, slides = render_pptx(_plan(), sources)
    validate_generated_document(docx, "docx", max_bytes=10 * 1024 * 1024)
    validate_generated_document(pptx, "pptx", max_bytes=10 * 1024 * 1024)
    assert Document(BytesIO(docx)).paragraphs[0].text == "高血压预防科普"
    assert len(Presentation(BytesIO(pptx)).slides) == slides
    assert slides >= 5


async def _create_request(client, user_id):
    client.cookies.set(ACCESS_COOKIE, create_access_token(user_id))
    consultation = await client.post(
        "/api/v1/consultations",
        json={"clientRequestId": str(uuid4())},
    )
    cid = UUID(consultation.json()["id"])
    message = await client.post(
        f"/api/v1/consultations/{cid}/messages",
        json={
            "clientRequestId": str(uuid4()),
            "content": "帮我生成一份高血压预防 PPT 和 Word",
        },
    )
    assert message.status_code == 201
    assert message.json()["documentGenerationIntent"] is True
    assert message.json()["imageGenerationIntent"] is False
    return cid, UUID(message.json()["id"])


async def test_create_is_idempotent_notice_guarded_and_user_isolated(profile_context):
    client, db, (user, other) = profile_context
    cid, message_id = await _create_request(client, user.id)
    payload = {
        "clientRequestId": str(uuid4()),
        "sourceMessageId": str(message_id),
        "noticeAccepted": True,
        "noticeVersion": "document-generation-v1",
    }
    missing = await client.post(
        f"/api/v1/consultations/{cid}/document-generations",
        json={**payload, "noticeAccepted": False},
    )
    assert missing.status_code == 422
    assert missing.json()["code"] == "DOCUMENT_GENERATION_NOTICE_REQUIRED"
    first = await client.post(
        f"/api/v1/consultations/{cid}/document-generations",
        json=payload,
    )
    second = await client.post(
        f"/api/v1/consultations/{cid}/document-generations",
        json=payload,
    )
    replayed_source = await client.post(
        f"/api/v1/consultations/{cid}/document-generations",
        json={**payload, "clientRequestId": str(uuid4())},
    )
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert replayed_source.status_code == 202
    assert replayed_source.json()["id"] == first.json()["id"]
    assert first.json()["formats"] == ["docx", "pptx"]
    row = await db.get(GeneratedDocument, UUID(first.json()["id"]))
    assert row is not None and row.status == "queued"
    assert row.title_ciphertext is None

    client.cookies.set(ACCESS_COOKIE, create_access_token(other.id))
    hidden = await client.get(f"/api/v1/document-generations/{row.id}")
    assert hidden.status_code == 404


async def test_worker_generates_encrypted_files_downloads_and_deletes(
    profile_context,
    tmp_path,
    monkeypatch,
):
    client, db, (user, _) = profile_context
    settings = get_settings()
    monkeypatch.setattr(settings, "document_generation_storage_dir", str(tmp_path))
    cid, message_id = await _create_request(client, user.id)
    created = await client.post(
        f"/api/v1/consultations/{cid}/document-generations",
        json={
            "clientRequestId": str(uuid4()),
            "sourceMessageId": str(message_id),
            "noticeAccepted": True,
            "noticeVersion": "document-generation-v1",
        },
    )
    generation_id = UUID(created.json()["id"])

    async def fake_search(_db, query, **kwargs):
        assert "高血压" in query
        return RetrievalResult(
            query_redacted=False,
            model="test",
            version="test",
            items=[_citation()],
        )

    async def fake_plan(topic, citations):
        assert "高血压" in topic
        assert len(citations) == 1
        return _plan()

    monkeypatch.setattr(generation_service, "search_knowledge", fake_search)
    monkeypatch.setattr(generation_service, "generate_content_plan", fake_plan)
    assert await generation_service.process_one(db, generation_id) is True

    status = await client.get(f"/api/v1/document-generations/{generation_id}")
    assert status.status_code == 200
    payload = status.json()
    assert payload["status"] == "completed"
    assert payload["title"] == "高血压预防科普"
    assert payload["sourceCount"] == 1
    assert payload["expiresAt"] is not None
    assert [item["format"] for item in payload["files"]] == ["docx", "pptx"]
    assert payload["files"][0]["pageCount"] is None
    assert payload["files"][1]["pageCount"] >= 5

    rows = (
        await db.scalars(
            select(GeneratedDocumentFile).where(
                GeneratedDocumentFile.generation_id == generation_id
            )
        )
    ).all()
    assert len(rows) == 2
    for row in rows:
        stored = tmp_path / row.storage_key
        assert stored.exists()
        assert stored.read_bytes()[:2] != b"PK"
        response = await client.get(
            f"/api/v1/document-generations/{generation_id}/files/{row.id}/content"
        )
        assert response.status_code == 200
        assert response.content[:2] == b"PK"
        assert response.headers["cache-control"] == "no-store, private"
        assert response.headers["content-disposition"].startswith("attachment;")

    listed = await client.get(f"/api/v1/consultations/{cid}/document-generations")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["sourceMessageId"] == str(message_id)

    deleted = await client.delete(f"/api/v1/document-generations/{generation_id}")
    assert deleted.status_code == 204
    assert all(not (tmp_path / row.storage_key).exists() for row in rows)


async def test_worker_fails_without_evidence(profile_context, monkeypatch):
    client, db, (user, _) = profile_context
    cid, message_id = await _create_request(client, user.id)
    created = await client.post(
        f"/api/v1/consultations/{cid}/document-generations",
        json={
            "clientRequestId": str(uuid4()),
            "sourceMessageId": str(message_id),
            "noticeAccepted": True,
            "noticeVersion": "document-generation-v1",
        },
    )
    generation_id = UUID(created.json()["id"])

    async def no_results(*args, **kwargs):
        return RetrievalResult(
            query_redacted=False,
            model="test",
            version="test",
            items=[],
        )

    monkeypatch.setattr(generation_service, "search_knowledge", no_results)
    assert await generation_service.process_one(db, generation_id) is False
    row = await db.get(GeneratedDocument, generation_id)
    await db.refresh(row)
    assert row.status == "failed"
    assert row.error_code == "DOCUMENT_EVIDENCE_INSUFFICIENT"


async def test_worker_does_not_reclaim_queued_task_with_live_lease(profile_context):
    client, db, (user, _) = profile_context
    cid, message_id = await _create_request(client, user.id)
    created = await client.post(
        f"/api/v1/consultations/{cid}/document-generations",
        json={
            "clientRequestId": str(uuid4()),
            "sourceMessageId": str(message_id),
            "noticeAccepted": True,
            "noticeVersion": "document-generation-v1",
        },
    )
    generation_id = UUID(created.json()["id"])
    row = await db.get(GeneratedDocument, generation_id)
    row.lease_owner = "another-worker"
    row.lease_expires_at = datetime.now(UTC) + timedelta(minutes=2)
    await db.commit()

    assert await generation_service.process_due(db, limit=10) == (0, 0)
    await db.refresh(row)
    assert row.status == "queued"
    assert row.lease_owner == "another-worker"


async def test_orphaned_generated_document_files_are_queued_and_deleted(
    profile_context,
    tmp_path,
    monkeypatch,
):
    _, db, _ = profile_context
    monkeypatch.setattr(get_settings(), "document_generation_storage_dir", str(tmp_path))
    storage_dir = tmp_path / "files" / "aa"
    storage_dir.mkdir(parents=True)
    orphan = storage_dir / "orphan.bin"
    temporary = storage_dir / "interrupted.tmp"
    orphan.write_bytes(b"encrypted")
    temporary.write_bytes(b"partial")
    stale = (datetime.now(UTC) - timedelta(hours=2)).timestamp()
    os.utime(orphan, (stale, stale))
    os.utime(temporary, (stale, stale))

    found = await reconcile_orphaned_generated_documents(
        db,
        older_than=datetime.now(UTC) - timedelta(hours=1),
    )
    assert found == 2
    jobs = (await db.scalars(select(GeneratedDocumentDeletionJob))).all()
    assert {job.storage_key for job in jobs} == {
        "files/aa/orphan.bin",
        "files/aa/interrupted.tmp",
    }

    deleted = await process_document_deletion_jobs(db)
    assert deleted.completed == 2
    assert not orphan.exists()
    assert not temporary.exists()


def test_document_generation_migration_refuses_unsafe_downgrade(monkeypatch):
    migration = importlib.import_module(
        "migrations.versions.20260927_0024_generated_documents"
    )

    class Bind:
        @staticmethod
        def scalar(statement):
            assert "generated_documents" in str(statement)
            return 1

    monkeypatch.setattr(migration.op, "get_bind", lambda: Bind())
    with pytest.raises(RuntimeError, match="generated document data exists"):
        migration.downgrade()


def test_generated_document_default_retention_is_30_days():
    assert get_settings().document_generation_retention_days == 30


def test_content_plan_rejects_unknown_source_number():
    invalid = _plan().model_copy(deep=True)
    invalid.sections[0].source_ids = [2]
    from app.services.document_generation_content import _validate_source_ids

    with pytest.raises(AppError) as raised:
        _validate_source_ids(invalid, 1)
    assert raised.value.code == "DOCUMENT_MODEL_INVALID_RESPONSE"
