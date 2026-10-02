"""知识图谱治理层的输入模型（G1 只有受控 CLI 使用，不对外暴露写接口）。"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.knowledge_graph import ConceptType
from app.services.knowledge_graph_vocabulary import (
    KnowledgeGraphVocabularyError,
    normalize_concept_name,
)


class GraphConceptSeed(BaseModel):
    """一条人工维护的概念登记。别名必须来自审核资料或人工维护。"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    concept_type: ConceptType = Field(alias="conceptType")
    canonical_name: str = Field(alias="canonicalName", min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("canonical_name", mode="before")
    @classmethod
    def trim_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("aliases", mode="before")
    @classmethod
    def trim_aliases(cls, value: object) -> object:
        if isinstance(value, list):
            return [item.strip() if isinstance(item, str) else item for item in value]
        return value

    @field_validator("canonical_name", "aliases")
    @classmethod
    def require_normalizable(cls, value: object) -> object:
        """规范化后为空的名字直接拒绝——空别名会在检索里匹配到一切。"""

        items = value if isinstance(value, list) else [value]
        for item in items:
            if not isinstance(item, str):
                continue
            try:
                normalize_concept_name(item)
            except KnowledgeGraphVocabularyError as exc:
                raise ValueError(str(exc)) from exc
        return value


class GraphConceptSeedFile(BaseModel):
    """`knowledge-graph-cli seed-concepts` 读取的登记文件。"""

    model_config = ConfigDict(extra="forbid")

    concepts: list[GraphConceptSeed] = Field(min_length=1)