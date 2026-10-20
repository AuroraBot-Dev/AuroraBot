"""训练输入的解析内容摘要与可选原始资源来源。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from aurorabot.contracts.artifact_codec import artifact_data
from aurorabot.contracts.identity import is_namespace

if TYPE_CHECKING:
    from aurorabot.contracts.artifact import ArtifactInfo

_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class TrainingProvenance:
    """原始字节版本和解析后输入摘要各自保留，不以路径或经历 ID 代替。"""

    domain: str
    training_digest: str
    validation_digest: str
    training_source: ArtifactInfo | None = None
    validation_source: ArtifactInfo | None = None

    def __post_init__(self) -> None:
        """来源资源必须属于相同领域的数据集，两侧来源必须一同给出。"""
        if not is_namespace(self.domain) or any(
            _SHA256.fullmatch(value) is None for value in (self.training_digest, self.validation_digest)
        ):
            raise ValueError("训练来源需要有效领域和完整输入摘要")
        if (self.training_source is None) != (self.validation_source is None):
            raise ValueError("训练集和验证集的资源来源必须一同给出")
        for source in (self.training_source, self.validation_source):
            if source is not None and (source.ref.key.domain, source.ref.key.kind) != (self.domain, "dataset"):
                raise ValueError("训练来源必须引用同一领域的 dataset 资源")


def bind_training_provenance(
    domain: str, training_digest: str, validation_digest: str, declared: TrainingProvenance | None
) -> TrainingProvenance:
    """训练器以实际样本重新计算摘要，声明不能替换本次真正使用的输入。"""
    if declared is not None:
        if (declared.domain, declared.training_digest, declared.validation_digest) != (
            domain,
            training_digest,
            validation_digest,
        ):
            raise ValueError("声明的数据来源与实际训练输入不一致")
        return declared
    return TrainingProvenance(domain, training_digest, validation_digest)


def provenance_data(provenance: TrainingProvenance) -> dict[str, Any]:
    """可独立审查的来源格式，未发布原始资源时明确保留空值。"""
    return {
        "schema_version": 1,
        "domain": provenance.domain,
        "training": {
            "input_digest": provenance.training_digest,
            "source": artifact_data(provenance.training_source) if provenance.training_source is not None else None,
        },
        "validation": {
            "input_digest": provenance.validation_digest,
            "source": artifact_data(provenance.validation_source) if provenance.validation_source is not None else None,
        },
    }
