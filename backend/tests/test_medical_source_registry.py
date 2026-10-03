import json
from pathlib import Path
from urllib.parse import urlparse

REGISTRY_PATH = (
    Path(__file__).resolve().parents[1] / "docs" / "medical_source_registry.json"
)
INTAKE_PLAN_PATH = (
    Path(__file__).resolve().parents[1] / "docs" / "official_summary_intake_plan.json"
)
CANDIDATES_PATH = (
    Path(__file__).resolve().parents[1] / "docs" / "official_summary_candidates.json"
)
TRUSTED_DOMAINS = {
    "app.gjzwfw.gov.cn",
    # 2026-10-03 用户批准扩充：养生健身知识储备的 3 个国家级来源（中国营养学会 /
    # 国家体育总局 / 国家中医药管理局）。这三条仅是**登记**，未加入
    # approved_for_ingestion，仍需真实医学审核后才能导入。福建卫健委转载稿已按
    # 用户决定暂缓，未加入本白名单。
    "dg.cnsoc.org",
    "www.chinacdc.cn",
    "www.natcm.gov.cn",
    "www.ndcpa.gov.cn",
    "www.nhc.gov.cn",
    "www.nmpa.gov.cn",
    "www.sport.gov.cn",
    "www.who.int",
}


def load_registry() -> dict[str, object]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_medical_source_registry_uses_unique_official_https_channels():
    registry = load_registry()
    sources = registry["sources"]
    source_ids = [source["id"] for source in sources]

    assert len(sources) >= 7
    assert len(source_ids) == len(set(source_ids))
    for source in sources:
        parsed = urlparse(source["entry_url"])
        assert parsed.scheme == "https"
        assert parsed.hostname in TRUSTED_DOMAINS


def test_approved_sources_remain_manual_summary_only():
    registry = load_registry()

    assert registry["policy"]["automated_collection_enabled"] is False
    approved = set(registry["policy"]["approved_for_ingestion"])
    assert approved == {
        "nhc_health_literacy_2024",
        "nhc_clinical_guidance",
        "nmpa_drug_verification",
    }
    assert all(source["automated_collection"] is False for source in registry["sources"])
    for source in registry["sources"]:
        if source["id"] not in approved:
            continue
        policy = source["ingestion_policy"]
        assert policy["allowed_content_modes"] == ["original_summary"]
        assert policy["require_source_attribution"] is True
        assert policy["max_verbatim_quote_chars_total"] <= 100


def test_initial_official_summary_intake_is_capped_and_balanced():
    plan = json.loads(INTAKE_PLAN_PATH.read_text(encoding="utf-8"))
    allocations = plan["allocation_by_document_type"]
    coverage = plan["coverage_targets"]

    assert sum(item["limit"] for item in allocations) == plan["initial_batch_total"] == 30
    assert plan["policy"]["max_documents_per_review_round"] == 5
    assert all(item["limit"] > 0 for item in allocations)
    assert sum(item["minimum"] for item in coverage) == 30


def test_official_candidates_are_summary_only_and_link_to_official_pages():
    payload = json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))

    assert payload["status"] == "pending_qualified_medical_review"
    assert len(payload["candidates"]) == 10
    for candidate in payload["candidates"]:
        parsed = urlparse(candidate["canonical_url"])
        assert parsed.scheme == "https"
        assert parsed.hostname in {"www.nhc.gov.cn", "app.gjzwfw.gov.cn"}
        assert candidate["summary_draft"]
        assert candidate["status"] == "pending_qualified_medical_review"
        assert sum(len(quote) for quote in candidate["verbatim_quotes"]) <= 100
