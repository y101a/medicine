"""Offline prototype candidate checks require no database or network."""

from app.knowledge_graph_candidate_check import build_evaluation_manifest, check_package


def _package(evidence: str = "发热常伴不适") -> dict:
    return {"topics": [{
        "topic_key": "fever",
        "excerpts": ["发热常伴不适"],
        "concepts": [
            {"concept_type": "topic", "canonical_name": "发热"},
            {"concept_type": "symptom", "canonical_name": "不适", "evidence": evidence},
        ],
        "candidate_triples": [{
            "subject": "发热", "predicate": "MAY_INCLUDE_SYMPTOM", "object": "不适",
            "evidence_excerpt": "发热常伴不适",
            "review": {"decision": "pending"},
        }],
    }]}


def test_valid_package_has_no_issue() -> None:
    result = check_package(_package())
    assert (result["topics"], result["concepts"], result["triples"]) == (1, 2, 1)
    assert result["issues"] == []


def test_missing_excerpt_is_reported() -> None:
    result = check_package(_package("不存在的原文"))
    assert [issue["code"] for issue in result["issues"]] == ["EVIDENCE_NOT_IN_EXCERPTS"]


def test_invalid_relation_and_nonpending_are_reported() -> None:
    package = _package()
    triple = package["topics"][0]["candidate_triples"][0]
    triple["predicate"] = "CAUSES"
    triple["review"]["decision"] = "approved"
    codes = {issue["code"] for issue in check_package(package)["issues"]}
    assert codes == {"INVALID_TRIPLE", "NOT_PENDING"}


def test_malformed_items_return_issues_instead_of_crashing() -> None:
    result = check_package({"topics": [None, {"topic_key": "x", "concepts": [None],
                                               "candidate_triples": [None]}]})
    assert {issue["code"] for issue in result["issues"]} == {
        "INVALID_TOPIC", "INVALID_CONCEPT", "INVALID_TRIPLE"
    }


def test_evaluation_manifest_is_unreviewed_and_not_publishable() -> None:
    package = _package()
    package["status"] = "all_candidates_pending_human_review"
    package["topics"][0]["source"] = {"url": "https://example.org/fever"}
    result = build_evaluation_manifest(package)
    assert result["ok"] is True
    assert result["medical_review_label"] == "暂未经专业医学审核"
    assert result["data_scope"] == "evaluation_only"
    assert result["eligible_for_publication"] is False
    assert result["topics"][0]["candidate_triples"][0]["review"]["decision"] == "pending"


def test_evaluation_manifest_rejects_approved_or_missing_source() -> None:
    package = _package()
    package["status"] = "all_candidates_pending_human_review"
    package["topics"][0]["candidate_triples"][0]["review"]["decision"] = "approved"
    result = build_evaluation_manifest(package)
    assert result["ok"] is False
    assert {issue["code"] for issue in result["issues"]} == {
        "NOT_PENDING", "MISSING_PUBLIC_SOURCE"
    }
    assert "topics" not in result
