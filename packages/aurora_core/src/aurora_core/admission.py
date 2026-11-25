"""声明接入诊断；登记接收成功不代表实例已经连接或运行。"""

import logging
from dataclasses import dataclass
from enum import StrEnum

from .bootstrap import Receiver
from .ids import Id
from .registry import DefinitionRegistry

logger = logging.getLogger(__name__)


class AdmissionStatus(StrEnum):
    ACCEPTED = "accepted"
    UNCONNECTED = "unconnected"
    REJECTED = "rejected"


@dataclass(frozen=True)
class Admission:
    """一条登记或插槽声明的接收结果。"""

    source: Id
    provider: str
    relation: str
    target: Id
    status: AdmissionStatus
    reason: str | None = None


def inspect_admissions(registry: DefinitionRegistry) -> tuple[Admission, ...]:
    """检查整张总表中的声明，保留缺席目标并输出告警。

    接收规则只评估声明，不创建实例连接，不调用处理器；实例连接由宿主的连接机制建立。
    """
    results: list[Admission] = []
    for entry in registry.entries():
        for relation, identity, kind in (
            ("register_to", entry.register_to, "registry"),
            ("slot", entry.slot, "hook_slot"),
        ):
            if identity is None:
                continue
            reason = None
            try:
                receiver = registry.get(identity)
            except KeyError:
                status = AdmissionStatus.UNCONNECTED
                reason = "接收方缺席"
            else:
                if receiver.kind != kind or not isinstance(receiver.target, Receiver):
                    reason = f"目标不是提供接收规则的 {kind}"
                else:
                    reason = receiver.target.rejection_reason(entry)
                status = AdmissionStatus.REJECTED if reason is not None else AdmissionStatus.ACCEPTED
            result = Admission(entry.id, entry.provider, relation, identity, status, reason)
            results.append(result)
            if status != AdmissionStatus.ACCEPTED:
                logger.warning(
                    "提供者 %s 的 %s 经 %s 指向 %s：%s（%s）",
                    entry.provider,
                    entry.id,
                    relation,
                    identity,
                    status,
                    reason,
                )
    return tuple(results)
