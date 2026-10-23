"""Read-only checks for a prototype graph candidate package.

This tool never changes review status and does not connect to PostgreSQL or Neo4j.
It checks only package-internal consistency, not medical truth or source-page rights.
"""

import argparse
import json
from pathlib import Path

from app.services.knowledge_graph_vocabulary import (
    KnowledgeGraphVocabularyError,
    normalize_concept_name,
    validate_triple,
)


def check_package(package: dict) -> dict:
    issues: list[dict[str, str]] = []
    topics = package.get("topics")
    if not isinstance(topics, list):
        return {"topics": 0, "concepts": 0, "triples": 0, "issues": [
            {"topic": "", "code": "INVALID_TOPICS", "detail": "topics must be a list"}
        ]}

    concept_count = 0
    triple_count = 0
    for topic in topics:
        if not isinstance(topic, dict):
            issues.append({
                "topic": "", "code": "INVALID_TOPIC", "detail": "topic must be an object"
            })
            continue
        key = str(topic.get("topic_key", ""))
        excerpts = topic.get("excerpts", [])
        if not isinstance(excerpts, list):
            excerpts = []
        concepts = topic.get("concepts", [])
        triples = topic.get("candidate_triples", [])
        if not isinstance(concepts, list) or not isinstance(triples, list):
            issues.append({
                "topic": key,
                "code": "INVALID_COLLECTION",
                "detail": "concepts/triples must be lists",
            })
            continue
        names: dict[str, str] = {}
        for concept in concepts:
            concept_count += 1
            if not isinstance(concept, dict):
                issues.append({"topic": key, "code": "INVALID_CONCEPT", "detail": "not an object"})
                continue
            name = str(concept.get("canonical_name", ""))
            kind = str(concept.get("concept_type", ""))
            try:
                normalized = normalize_concept_name(name)
            except KnowledgeGraphVocabularyError:
                issues.append({"topic": key, "code": "INVALID_CONCEPT_NAME", "detail": name})
                continue
            if normalized in names and names[normalized] != kind:
                issues.append({"topic": key, "code": "AMBIGUOUS_CONCEPT", "detail": name})
            names[normalized] = kind
            evidence = concept.get("evidence")
            if evidence and not any(str(evidence) in str(excerpt) for excerpt in excerpts):
                issues.append({"topic": key, "code": "EVIDENCE_NOT_IN_EXCERPTS", "detail": name})
        for triple in triples:
            triple_count += 1
            if not isinstance(triple, dict):
                issues.append({"topic": key, "code": "INVALID_TRIPLE", "detail": "not an object"})
                continue
            subject = str(triple.get("subject", ""))
            obj = str(triple.get("object", ""))
            try:
                subject_type = names[normalize_concept_name(subject)]
                object_type = names[normalize_concept_name(obj)]
            except (KeyError, KnowledgeGraphVocabularyError):
                issues.append({
                    "topic": key, "code": "UNKNOWN_ENDPOINT", "detail": f"{subject} -> {obj}"
                })
                continue
            try:
                validate_triple(subject_type, str(triple.get("predicate", "")), object_type)
            except KnowledgeGraphVocabularyError as exc:
                issues.append({"topic": key, "code": "INVALID_TRIPLE", "detail": str(exc)})
            review = triple.get("review")
            if not isinstance(review, dict) or review.get("decision") != "pending":
                issues.append({
                    "topic": key, "code": "NOT_PENDING", "detail": f"{subject} -> {obj}"
                })
    return {
        "topics": len(topics), "concepts": concept_count,
        "triples": triple_count, "issues": issues,
    }


def build_evaluation_manifest(package: dict) -> dict:
    """Prepare explicitly unreviewed, offline-only data; never publish it."""

    checked = check_package(package)
    issues = list(checked["issues"])
    topics = package.get("topics", [])
    if package.get("status") != "all_candidates_pending_human_review":
        issues.append({
            "topic": "", "code": "NOT_PENDING_PACKAGE",
            "detail": "evaluation input must be a pending candidate package",
        })
    for topic in topics if isinstance(topics, list) else []:
        if not isinstance(topic, dict):
            continue
        source = topic.get("source")
        if not isinstance(source, dict) or not str(source.get("url", "")).startswith("https://"):
            issues.append({
                "topic": str(topic.get("topic_key", "")), "code": "MISSING_PUBLIC_SOURCE",
                "detail": "a public HTTPS source URL is required",
            })
        if not topic.get("excerpts"):
            issues.append({
                "topic": str(topic.get("topic_key", "")), "code": "MISSING_EXCERPTS",
                "detail": "source excerpts are required",
            })
        for triple in topic.get("candidate_triples", []):
            if not isinstance(triple, dict):
                continue
            evidence = triple.get("evidence_excerpt")
            if not isinstance(evidence, str) or not any(
                evidence and evidence in excerpt
                for excerpt in topic.get("excerpts", [])
                if isinstance(excerpt, str)
            ):
                issues.append({
                    "topic": str(topic.get("topic_key", "")),
                    "code": "TRIPLE_EVIDENCE_NOT_IN_EXCERPTS",
                    "detail": f"{triple.get('subject', '')} -> {triple.get('object', '')}",
                })
    if issues:
        return {
            "ok": False, "data_scope": "evaluation_only",
            "medical_review_label": "暂未经专业医学审核",
            "eligible_for_publication": False, "issues": issues,
        }
    return {
        "ok": True,
        "data_scope": "evaluation_only",
        "medical_review_label": "暂未经专业医学审核",
        "eligible_for_publication": False,
        "topics": [
            {
                "topic_key": topic["topic_key"],
                "source": topic["source"],
                "excerpts": topic["excerpts"],
                "candidate_triples": topic["candidate_triples"],
            }
            for topic in topics
        ],
        "issues": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only prototype graph candidate check")
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument(
        "--evaluation-manifest", action="store_true",
        help="emit an unreviewed, evaluation-only manifest; never writes to databases",
    )
    args = parser.parse_args()
    try:
        package = json.loads(args.file.read_text(encoding="utf-8"))
        if not isinstance(package, dict):
            raise ValueError("root must be an object")
        result = (build_evaluation_manifest(package) if args.evaluation_manifest
                  else check_package(package))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": not result["issues"], **result}, ensure_ascii=False))
    return 0 if not result["issues"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
