from pydantic import BaseModel, ConfigDict, Field


class VoiceTranscriptionOut(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)

    text: str = Field(min_length=1, max_length=4000)
    duration_ms: int = Field(serialization_alias="durationMs", ge=1, le=60_500)
