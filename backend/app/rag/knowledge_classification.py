"""公共医学文档的用途分类；与审核状态、图谱概念类型正交。"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class KnowledgeLayer(StrEnum):
    DISEASE = "disease"
    PHYSIOLOGY = "physiology"
    PHARMACOLOGY = "pharmacology"
    WELLNESS_FITNESS = "wellness_fitness"


class KnowledgeClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_layer: KnowledgeLayer
    secondary_layers: list[KnowledgeLayer] = Field(default_factory=list, max_length=3)
    topic_key: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$")

    @field_validator("secondary_layers")
    @classmethod
    def unique_layers(cls, layers: list[KnowledgeLayer]) -> list[KnowledgeLayer]:
        if len(layers) != len(set(layers)):
            raise ValueError("secondary_layers 不能重复")
        return layers

    @model_validator(mode="after")
    def no_primary_duplicate(self) -> "KnowledgeClassification":
        if self.primary_layer in self.secondary_layers:
            raise ValueError("primary_layer 不能出现在 secondary_layers")
        return self
