from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SpeechPreset(StrEnum):
    MANDARIN_FEMALE = "mandarin_female"
    MANDARIN_MALE = "mandarin_male"
    SHANGHAI = "shanghai"
    CANTONESE = "cantonese"
    NORTHEAST = "northeast"
    CHONGQING = "chongqing"
    SHAANXI = "shaanxi"
    YUNNAN = "yunnan"
    NINGBO = "ningbo"
    GANSU = "gansu"


class SpeechOutputIntent(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True, extra="forbid")

    requested: Literal[True] = True
    speech_preset: SpeechPreset | None = Field(
        default=None,
        serialization_alias="speechPreset",
    )


class SpeechSynthesisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speech_preset: str = Field(alias="speechPreset", min_length=1, max_length=32)
    rate: Literal[0.8, 1.0, 1.2] = 1.0


class SpeechPresetOut(BaseModel):
    id: SpeechPreset
    label: str
    language: str
    dialect: str | None = None


class SpeechPresetListOut(BaseModel):
    default: SpeechPreset
    items: list[SpeechPresetOut]
