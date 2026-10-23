"""Bounded, content-free progress snapshots for coordinated AI workflows.

These are task roles, not independent clinical decision makers. Only an actual
completed step may be shown as completed; no raw health text enters snapshots.
"""

from __future__ import annotations

from typing import Any

from app.ai.bounded_workflow_plan import validate_workflow_plan

DOCUMENT_ROLES = (
    ("coordinator", "任务编排"),
    ("evidence", "证据检索"),
    ("planner", "章节规划"),
    ("writer", "内容撰写"),
    ("reviewer", "引用校验"),
    ("layout", "版式渲染"),
    ("delivery", "文件交付"),
)
CONSULTATION_ROLES = (
    ("triage", "安全分流"),
    ("evidence", "证据检索"),
    ("planner", "回答规划"),
    ("fallback", "证据不足兜底"),
    ("writer", "科普回答"),
    ("evidence_reviewer", "证据核查"),
    ("reviewer", "引用核验"),
)
DOCUMENT_STAGES = {"queued", "evidence", "planner", "writer", "reviewer", "layout", "delivery"}


def _snapshot(
    scene: str,
    roles: tuple[tuple[str, str], ...],
    statuses: dict[str, str],
    model_roles: frozenset[str] = frozenset(),
    edges: tuple[tuple[str, str], ...] | None = None,
) -> dict[str, Any]:
    links = edges or tuple(
        (roles[index][0], roles[index + 1][0]) for index in range(len(roles) - 1)
    )
    validate_workflow_plan(scene, roles, links)
    return {
        "scene": scene,
        "mode": "centralized",
        "version": 1,
        "nodes": [
            {
                "id": role_id,
                "label": label,
                "status": statuses.get(role_id, "pending"),
                "executor": "model" if role_id in model_roles else "code",
            }
            for role_id, label in roles
        ],
        "edges": [{"from": source, "to": target} for source, target in links],
    }


def document_workflow(
    status: str, stage: str | None, *, specialist_models_enabled: bool = False
) -> dict[str, Any]:
    """Map persisted worker checkpoints to truthful, display-safe progress."""
    if stage not in DOCUMENT_STAGES:
        stage = "queued"
    role_ids = [role_id for role_id, _ in DOCUMENT_ROLES]
    active = {
        "queued": "coordinator",
        "evidence": "evidence",
        "planner": "planner",
        "writer": "writer",
        "reviewer": "reviewer",
        "layout": "layout",
        "delivery": "delivery",
    }[stage]
    active_index = role_ids.index(active)
    statuses = {
        role_id: "completed" if index < active_index else "pending"
        for index, role_id in enumerate(role_ids)
    }
    if status == "completed":
        statuses = dict.fromkeys(role_ids, "completed")
    elif status in {"failed", "cancelled", "expired"}:
        statuses[active] = status
    elif status == "queued":
        statuses["coordinator"] = "queued"
    else:
        statuses[active] = "running"
    if not specialist_models_enabled:
        statuses["planner"] = "skipped"
    model_roles = (
        frozenset({"writer", "planner", "reviewer"})
        if specialist_models_enabled
        else frozenset({"writer"})
    )
    return _snapshot("document_generation", DOCUMENT_ROLES, statuses, model_roles)


def consultation_workflow(
    graph_result: dict[str, Any],
    *,
    safety_reply: bool,
    phase: str = "streaming",
    planner_status: str = "skipped",
    evidence_reviewer_status: str = "skipped",
) -> dict[str, Any]:
    """Expose only stages already executed by the existing safety/RAG path."""
    retrieval = graph_result.get("retrieval_status", "skipped")
    statuses = {
        "triage": "completed",
        "evidence": (
            retrieval if retrieval in {"completed", "empty", "failed", "skipped"} else "failed"
        ),
        "planner": planner_status,
        "fallback": "completed" if safety_reply else "skipped",
        "writer": "skipped" if safety_reply else "running",
        "evidence_reviewer": evidence_reviewer_status,
        "reviewer": "pending",
    }
    if phase in {"completed", "failed", "stopped"}:
        statuses["writer"] = "skipped" if safety_reply else phase
        statuses["reviewer"] = "completed" if phase == "completed" else "skipped"
    model_roles = {"writer"}
    if planner_status == "completed":
        model_roles.add("planner")
    if evidence_reviewer_status != "skipped":
        model_roles.add("evidence_reviewer")
    links = (
        ("triage", "evidence"),
        ("evidence", "planner"),
        ("evidence", "fallback"),
        ("planner", "writer"),
        ("writer", "evidence_reviewer"),
        ("evidence_reviewer", "reviewer"),
        ("fallback", "reviewer"),
    )
    return _snapshot("consultation", CONSULTATION_ROLES, statuses, frozenset(model_roles), links)
