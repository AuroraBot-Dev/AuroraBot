"""按完整交流段选择模型请求历史，不修改持久消息或拆散工具往返。"""

from copy import deepcopy

from aurora_adapter.model import ChatRequest, Message
from aurora_adapter.model.content import MAX_FILE_BYTES, request_size
from aurora_core.json_data import encode_json


def read_exchange_ends(messages: list[Message], value: object) -> list[int]:
    """校验相对持久历史的结束位置，不允许越界、重复或切断工具往返。"""
    if not isinstance(value, list):
        raise TypeError("交流结束位置必须为列表")
    previous = 0
    for end in value:
        if type(end) is not int or not previous < end <= len(messages):
            raise ValueError("交流结束位置必须为递增且不越界的正整数")
        if messages[end - 1].get("tool_calls") or (end < len(messages) and messages[end]["role"] == "tool"):
            raise ValueError("交流结束位置不能切断工具往返")
        previous = end
    return value


class ModelInputBudgetExceeded(ValueError):
    """固定输入和当前交流段无法放入预算；异常只包含长度，不包含业务内容。"""

    def __init__(
        self, max_chars: int, required_chars: int, file_bytes: int = 0, *, breakdown: dict[str, int] | None = None
    ) -> None:
        self.max_chars, self.required_chars = max_chars, required_chars
        self.file_bytes, self.breakdown = file_bytes, breakdown or {}
        super().__init__(
            f"模型输入预算不足：需要 {required_chars} 字符和 {file_bytes} 附件字节，预算为 {max_chars} 字符及 {MAX_FILE_BYTES} 附件字节"
            f"；分项字符数：{self.breakdown}"
        )


class ModelInputBudget:
    """限制请求文本 JSON 字符及 10 MiB 内嵌文件，不等同于供应商 token。

    system、临时观察及工具定义完整保留。按显式正常结束位置选择完整交流段；
    未提供位置时仅识别无工具调用的 assistant 消息，至少保留最新交流段。
    省略提示计入预算，不生成摘要，不修改原请求或持久历史。
    """

    def __init__(self, max_chars: int) -> None:
        if type(max_chars) is not int or max_chars < 1024:
            raise ValueError("完整模型输入预算必须为至少 1024 的整数")
        self.max_chars = max_chars

    def exceeded(self, request: ChatRequest, history_start: int) -> ModelInputBudgetExceeded:
        """只报告长度；分项合计包含协议包装，不泄露输入或工具参数。"""
        chars, files = request_size(request)
        parts = {
            "system": 0,
            "view": 0,
            "history": 0,
            "tools": len(encode_json(request.get("tools", []))) if "tools" in request else 0,
        }
        empty_size = request_size({"messages": []})[0]
        for index, message in enumerate(request["messages"]):
            key = "history" if index >= history_start else "system" if message["role"] == "system" else "view"
            parts[key] += request_size({"messages": [message]})[0] - empty_size
        parts["overhead"] = chars - sum(parts.values())
        return ModelInputBudgetExceeded(self.max_chars, chars, files, breakdown=parts)

    def apply(self, request: ChatRequest, *, history_start: int, exchange_ends: list[int] | None = None) -> ChatRequest:
        messages = request["messages"]
        history = messages[history_start:]
        if exchange_ends is None:
            exchange_ends = [
                index + 1
                for index, message in enumerate(history)
                if message["role"] == "assistant" and not message.get("tool_calls")
            ]
        ends = read_exchange_ends(history, exchange_ends)

        def fits(candidate: ChatRequest) -> bool:
            chars, file_bytes = request_size(candidate)
            return chars <= self.max_chars and file_bytes <= MAX_FILE_BYTES

        if fits(request):
            return request
        boundaries = [end for end in ends if end < len(history)]

        def candidate_at(removed: int) -> ChatRequest:
            notice = {
                "kind": "input_budget",
                "omitted_messages": removed,
                "notice": "较早的完整交流段因输入预算省略；持久历史未删除，不代表事项已完成。",
            }
            candidate = deepcopy(request)
            candidate["messages"] = [
                *messages[:history_start],
                {"role": "user", "content": encode_json(notice)},
                *history[removed:],
            ]
            return candidate

        if not boundaries:
            raise self.exceeded(request, history_start)
        smallest = candidate_at(boundaries[-1])
        if not fits(smallest):
            required = min((request, smallest), key=lambda value: request_size(value)[0])
            raise self.exceeded(required, history_start)
        low, high = 0, len(boundaries) - 1
        while low < high:
            middle = (low + high) // 2
            if fits(candidate_at(boundaries[middle])):
                high = middle
            else:
                low = middle + 1
        return candidate_at(boundaries[low])
