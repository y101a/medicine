"""Validate the fixed, bounded role graph before exposing a workflow snapshot."""

from __future__ import annotations

from collections import defaultdict

_ALLOWED_ROLES = {
    "consultation": frozenset(
        {"triage", "evidence", "planner", "fallback", "writer", "evidence_reviewer", "reviewer"}
    ),
    "document_generation": frozenset(
        {"coordinator", "evidence", "planner", "writer", "reviewer", "layout", "delivery"}
    ),
}
MAX_WORKFLOW_NODES = 8


def validate_workflow_plan(
    scene: str,
    roles: tuple[tuple[str, str], ...],
    edges: tuple[tuple[str, str], ...],
) -> None:
    """Reject new tools/roles, duplicate IDs, missing endpoints and cycles."""
    allowed = _ALLOWED_ROLES.get(scene)
    ids = [role_id for role_id, _ in roles]
    if allowed is None or not 1 <= len(ids) <= MAX_WORKFLOW_NODES:
        raise ValueError("unsupported workflow plan")
    if len(set(ids)) != len(ids) or not set(ids).issubset(allowed):
        raise ValueError("workflow contains duplicate or unauthorized roles")
    if len(edges) > MAX_WORKFLOW_NODES * 2 or len(set(edges)) != len(edges):
        raise ValueError("workflow has too many or duplicate edges")
    graph: dict[str, list[str]] = defaultdict(list)
    for source, target in edges:
        if source not in ids or target not in ids or source == target:
            raise ValueError("workflow edge has an invalid endpoint")
        graph[source].append(target)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise ValueError("workflow contains a cycle")
        if node in visited:
            return
        visiting.add(node)
        for next_node in graph[node]:
            visit(next_node)
        visiting.remove(node)
        visited.add(node)

    for role_id in ids:
        visit(role_id)
