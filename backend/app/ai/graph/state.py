from typing import Literal, NotRequired, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

TriageRoute = Literal["emergency", "continue"]
NextStep = Literal["emergency_end", "generation_ready"]
RetrievalStatus = Literal["completed", "empty", "failed", "skipped"]
RetrievalGateReason = Literal[
    "medical_content",
    "non_medical_content",
    "emergency",
]


class RetrievalEvidence(TypedDict):
    source_key: str
    organization: str
    title: str
    canonical_url: str
    section_title: str | None
    content: str
    similarity: float
    trust_level: str
    keyword_score: NotRequired[float | None]
    vector_similarity: NotRequired[float | None]
    rerank_score: NotRequired[float | None]


class ConsultationGraphInput(TypedDict):
    """Private graph input. Raw health text must not be exposed in graph output."""

    user_text: str


class ConsultationGraphOutput(TypedDict):
    """Stable output contract consumed by the consultation service."""

    triage_route: TriageRoute
    triage_rule_version: str
    triage_rule_ids: list[str]
    triage_result: dict[str, object] | None
    next_step: NextStep


class ConsultationGraphState(ConsultationGraphInput, ConsultationGraphOutput):
    """Internal state shared by nodes while one graph invocation is running."""


class ConsultationGenerationGraphInput(TypedDict):
    """Private generation input; db and raw health text never appear in output."""

    user_text: str
    db: AsyncSession


class ConsultationGenerationGraphOutput(ConsultationGraphOutput):
    """Generation context returned to the streaming route."""

    retrieval_status: RetrievalStatus
    retrieval_items: list[RetrievalEvidence]
    retrieval_error_code: str | None
    retrieval_intent: bool
    retrieval_gate_reason: RetrievalGateReason
    web_search_status: Literal["skipped", "completed", "empty", "failed"]
    web_search_error_code: str | None


class ConsultationGenerationGraphState(
    ConsultationGenerationGraphInput,
    ConsultationGenerationGraphOutput,
):
    """Internal state for triage followed by controlled RAG retrieval."""
