"""Offline prototype candidate checks require no database or network."""

from app.knowledge_graph_candidate_check import check_package


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
