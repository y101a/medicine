"""Authenticated, read-only access to reviewed public graph relations."""

from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import CurrentUser, DbSession
from app.models.knowledge_graph import GraphClaimPredicate
from app.services.knowledge_graph_query import explore_public_graph, find_public_concepts

router = APIRouter(prefix="/knowledge-graph", tags=["公共医学知识图谱"])


class GraphExploreIn(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    concept_id: UUID = Field(alias="conceptId")
    relationship_types: list[GraphClaimPredicate] = Field(
        default_factory=lambda: list(GraphClaimPredicate), alias="relationshipTypes", max_length=5
    )
    depth: int = Field(default=1, ge=1, le=1)
    max_nodes: int = Field(default=30, alias="maxNodes", ge=1, le=30)


@router.get("/concepts")
async def concepts(
    user: CurrentUser,
    db: DbSession,
    query: str = Query(min_length=2, max_length=50),
) -> dict[str, list[dict[str, str]]]:
    del user
    items = await find_public_concepts(db, query)
    return {
        "items": [
            {"id": str(item.id), "name": item.canonical_name, "type": item.concept_type}
            for item in items
        ]
    }


@router.post("/explore")
async def explore(
    payload: GraphExploreIn,
    user: CurrentUser,
    db: DbSession,
) -> dict[str, object]:
    del user
    result = await explore_public_graph(
        db,
        payload.concept_id,
        predicates=tuple(item.value for item in payload.relationship_types),
    )
    relations = result.relations[: max(0, payload.max_nodes - 1)]
    return {
        "available": result.available,
        "revision": result.revision,
        "relations": [
            {
                "claimId": str(item.claim_id),
                "subject": {
                    "id": str(item.subject_id),
                    "name": item.subject_name,
                    "type": item.subject_type,
                },
                "object": {
                    "id": str(item.object_id),
                    "name": item.object_name,
                    "type": item.object_type,
                },
                "predicate": item.predicate,
                "evidence": list(item.evidence),
            }
            for item in relations
        ],
    }
