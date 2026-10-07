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


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only prototype graph candidate check")
    parser.add_argument("--file", required=True, type=Path)
    args = parser.parse_args()
    try:
        package = json.loads(args.file.read_text(encoding="utf-8"))
        if not isinstance(package, dict):
            raise ValueError("root must be an object")
        result = check_package(package)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": not result["issues"], **result}, ensure_ascii=False))
    return 0 if not result["issues"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
