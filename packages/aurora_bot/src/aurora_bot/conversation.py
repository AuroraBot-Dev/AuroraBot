"""直接交流的产品入口；回执只在当前插件会话保留，不承担运行调度。"""

from copy import deepcopy
from dataclasses import dataclass
from typing import cast
from uuid import uuid4

from aurora_adapter.model import JsonValue
from aurora_agent.react import AgentBusyError
from aurora_agent.runtime import Submission
from aurora_core import Id

from .attachments import message_content
from .conversation_contract import describe_conversation
from .operations import RunOperations

CONVERSATION = Id("org.aurora.bot:endpoints/conversation")
ENDPOINTS = Id("org.aurora.api:registries/endpoints")


class ConversationError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code = status, code


@dataclass(frozen=True)
class Receipt:
    payload: dict
    submission: Submission


class ConversationEndpoint:
    """同一会话不淘汰回执；达到上限拒绝新消息，旧消息仍可查询和去重。

    request_id 由客户端生成，作用域为 session_id/instance_id。接受文本和受限附件，
    不暴露任意 operation。回执不进入快照，重启后旧会话明确失效。
    """

    def __init__(self, operations: RunOperations, *, receipt_limit: int = 4096) -> None:
        if type(receipt_limit) is not int or receipt_limit <= 0:
            raise ValueError("回执上限必须为正整数")
        self.operations = operations
        self.session_id = uuid4().hex
        self.receipt_limit = receipt_limit
        self._receipts: dict[tuple[str, str], Receipt] = {}
        self.http = describe_conversation()["http"]

    async def handle(self, action: str, data: object) -> tuple[int, dict]:
        """校验产品信封并映射公开错误；成功返回接纳或查询结果。"""
        try:
            return 200, {"result": await self._handle(action, data)}
        except ConversationError as error:
            return error.status, {"error": {"code": error.code, "message": str(error)}}
        except AgentBusyError:
            return 409, {"error": {"code": "busy", "message": "运行正在收尾，请稍后提交"}}
        except LookupError:
            return 404, {"error": {"code": "not_found", "message": "目标实例或回执不存在"}}
        except RuntimeError:
            return 503, {"error": {"code": "unavailable", "message": "目标实例未启动或正在关闭"}}

    async def _handle(self, action: str, data: object) -> dict:
        fields = {
            "conversationInfo": set(),
            "conversationSubmit": {"session_id", "instance_id", "request_id", "text"},
            "conversationQuery": {"session_id", "instance_id", "request_id"},
            "conversationCancel": {"session_id", "instance_id", "run_id"},
        }
        if (
            action not in fields
            or not isinstance(data, dict)
            or set(data) - ({"files"} if action == "conversationSubmit" else set()) != fields[action]
        ):
            raise ConversationError(400, "invalid_request", "请求字段无效")
        for key, value in data.items():
            if key == "files":
                continue
            limit = 65536 if key == "text" else 256
            if not isinstance(value, str) or (key != "text" and not value.strip()) or len(value) > limit:
                raise ConversationError(400, "invalid_request", "字段须为长度受限的非空字符串")
        if action == "conversationInfo":
            return {"session_id": self.session_id, "instance_ids": list(self.operations.instances)}
        if data["session_id"] != self.session_id:
            raise ConversationError(409, "session_expired", "宿主会话已变更，请核对状态，不要自动重发")
        instance_id = data["instance_id"]
        if action == "conversationCancel":
            cancelled = await self.operations.cancel(data["run_id"], instance_id=instance_id)
            return {**data, "cancelled": cancelled}
        key = (instance_id, data["request_id"])
        if action == "conversationSubmit":
            try:
                content = message_content(data["text"], data.get("files", []))
            except (TypeError, ValueError):
                raise ConversationError(
                    400,
                    "invalid_request",
                    "附件须为支持的图片、PDF 或 UTF-8 文本，最多 8 个、合计 10 MiB；消息不能为空",
                ) from None
            payload = {"text": data["text"], "files": data.get("files", [])}
            receipt = self._receipts.get(key)
            if receipt is not None:
                if receipt.payload != payload:
                    raise ConversationError(409, "request_conflict", "request_id 已用于不同内容")
            else:
                if len(self._receipts) >= self.receipt_limit:
                    raise ConversationError(429, "receipt_limit", "当前会话回执已满，新消息未接纳")
                guidance = content if isinstance(content, str) else {"kind": "model_input", "content": content}
                submission = self.operations.submit(cast(JsonValue, guidance), instance_id=instance_id)
                receipt = Receipt(deepcopy(payload), submission)
                self._receipts[key] = receipt
        else:
            receipt = self._receipts[key]
        submission = receipt.submission
        result = {
            "session_id": self.session_id,
            "instance_id": instance_id,
            "request_id": data["request_id"],
            "guidance_id": submission.guidance_id,
            "sequence": submission.sequence,
            "run_id": submission.run.run_id,
            "accepted": True,
        }
        if action == "conversationQuery":
            completion = await submission.run.wait() if submission.run.done else None
            result["run_status"] = "pending" if completion is None else completion.status
            result["error"] = None if completion is None else completion.error
        return result
