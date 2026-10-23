"""Frozen, unreviewed graph evaluation material must stay separate from publication."""

import json
import re
from pathlib import Path

from app.knowledge_graph_candidate_check import build_evaluation_manifest
from app.knowledge_graph_evaluation import CASE_SETS

DOCS = Path(__file__).resolve().parents[1] / "docs"


def test_batch1_manifest_is_valid_but_never_publishable() -> None:
    package = json.loads((DOCS / "knowledge_graph_evaluation_batch1.json").read_text("utf-8"))
    manifest = build_evaluation_manifest(package)
    assert manifest["ok"] is True
    assert manifest["eligible_for_publication"] is False
    assert manifest["medical_review_label"] == "暂未经专业医学审核"
    assert len(manifest["topics"]) == 4
    assert sum(len(topic["candidate_triples"]) for topic in manifest["topics"]) == 9


def test_frozen_cases_cover_holdout_and_negative_routes() -> None:
    package = json.loads((DOCS / "knowledge_graph_evaluation_batch1.json").read_text("utf-8"))
    dataset = json.loads(
        (DOCS / "knowledge_graph_evaluation_batch1_cases.json").read_text("utf-8")
    )
    cases = dataset["cases"]
    assert dataset["status"] == "frozen_before_first_run"
    assert len(cases) == 18
    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["split"] for case in cases} == {"tune", "holdout"}
    assert {case["case_type"] for case in cases} >= {
        "supported", "unsupported", "confusable", "withdrawn"
    }
    topic_keys = {topic["topic_key"] for topic in package["topics"]}
    objects = {
        triple["object"] for topic in package["topics"]
        for triple in topic["candidate_triples"]
    }
    source_sentences = [
        excerpt for topic in package["topics"] for excerpt in topic["excerpts"]
    ]
    older_queries = {
        case["query"]
        for filename in (
            "medical_retrieval_evaluation_beijing_wjw_batch1.json",
            "medical_retrieval_evaluation_independent.json",
        )
        for case in json.loads((DOCS / filename).read_text("utf-8"))["cases"]
    }
    for case in cases:
        assert case["expected_source"] is None or case["expected_source"] in topic_keys
        assert set(case["expected_objects"]) <= objects
        assert case["query"].strip()
        assert case["query"] not in older_queries
        assert all(case["query"] not in excerpt for excerpt in source_sentences)


def test_batch2_expands_exact_unique_evaluation_questions_to_200() -> None:
    package = json.loads((DOCS / "knowledge_graph_evaluation_batch1.json").read_text("utf-8"))
    batch2 = json.loads(CASE_SETS["batch2"].read_text("utf-8"))
    cases = batch2["cases"]
    assert batch2["status"] == "frozen_before_first_run"
    assert batch2["medical_review_label"] == "暂未经专业医学审核"
    assert len(cases) == 51
    assert {case["split"] for case in cases} == {"holdout"}
    assert {case["case_type"] for case in cases} == {
        "supported", "unsupported", "confusable"
    }
    assert len({case["id"] for case in cases}) == len(cases)

    topic_sources = {
        triple["subject"]: topic["topic_key"]
        for topic in package["topics"]
        for triple in topic["candidate_triples"]
    }
    topic_objects = {
        triple["subject"]: {
            item["object"]
            for part in package["topics"]
            for item in part["candidate_triples"]
            if item["subject"] == triple["subject"]
        }
        for topic in package["topics"]
        for triple in topic["candidate_triples"]
    }
    all_relation_objects = {
        triple["object"] for topic in package["topics"]
        for triple in topic["candidate_triples"]
    }
    covered_objects = {
        item for case in cases for item in case["expected_objects"]
    }
    assert covered_objects == all_relation_objects
    source_sentences = [excerpt for topic in package["topics"] for excerpt in topic["excerpts"]]
    for case in cases:
        assert case["query"].strip()
        assert all(case["query"] not in excerpt for excerpt in source_sentences)
        if case["case_type"] == "supported":
            assert case["expected_topic"] in topic_sources
            assert case["expected_source"] == topic_sources[case["expected_topic"]]
            assert set(case["expected_objects"]) <= topic_objects[case["expected_topic"]]
        else:
            assert case["expected_objects"] == []
            assert case["expected_source"] is None

    all_cases = [
        case
        for filename in (
            "medical_retrieval_evaluation_v2.json",
            "medical_retrieval_evaluation_independent.json",
            "knowledge_graph_evaluation_batch1_cases.json",
            "knowledge_graph_evaluation_batch2_cases.json",
        )
        for case in json.loads((DOCS / filename).read_text("utf-8"))["cases"]
    ]
    normalized = [re.sub(r"[\W_]+", "", case["query"]).casefold() for case in all_cases]
    assert len(all_cases) == 200
    assert len(set(normalized)) == 200
