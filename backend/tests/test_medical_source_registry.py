import json
from pathlib import Path
from urllib.parse import urlparse

REGISTRY_PATH = (
    Path(__file__).resolve().parents[1] / "docs" / "medical_source_registry.json"
)
TRUSTED_DOMAINS = {
    "www.chinacdc.cn",
    "www.ndcpa.gov.cn",
    "www.nhc.gov.cn",
    "www.nmpa.gov.cn",
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


def test_no_source_can_be_automatically_ingested_before_review():
    registry = load_registry()

    assert registry["policy"]["automated_collection_enabled"] is False
    assert registry["policy"]["approved_for_ingestion"] == []
    assert all(source["automated_collection"] is False for source in registry["sources"])
