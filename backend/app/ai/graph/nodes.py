from app.ai.graph.state import ConsultationGraphInput, NextStep
from app.safety import evaluate_triage


def triage_node(state: ConsultationGraphInput) -> dict[str, object]:
    """Run deterministic red-flag checks before any future model node."""

    return evaluate_triage(state["user_text"]).as_langgraph_state()


def emergency_node(_state: object) -> dict[str, NextStep]:
    """Terminate AI generation when a red flag is active."""

    return {"next_step": "emergency_end"}


def generation_ready_node(_state: object) -> dict[str, NextStep]:
    """Mark the safe extension point for follow-up, RAG and model generation."""

    return {"next_step": "generation_ready"}
