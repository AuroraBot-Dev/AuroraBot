"""内容资源的有界结构化读写入口。"""

from __future__ import annotations

import base64
import codecs
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.contracts import ToolScopes
from src.contracts.artifact import MAX_ARTIFACT_CHUNK
from src.contracts.artifact_codec import artifact_data
from src.contracts.operation import OperationDefinition, OperationResult, OperationStatus
from src.contracts.resource import ResourceKey, ResourceRef
from src.utils.serialization import thaw_json

if TYPE_CHECKING:
    from src.contracts.artifact import ArtifactChunk
    from src.contracts.operation import OperationRequest
    from src.contracts.pkgs.artifacts import ArtifactStore

_MAX_BASE64 = ((MAX_ARTIFACT_CHUNK + 2) // 3) * 4


class ArtifactInput(BaseModel):
    """读取总是固定到调用方指定的内容摘要。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    key: str
    revision: str = Field(pattern="^[0-9a-f]{64}$")

    @property
    def ref(self) -> ResourceRef:
        """将协议输入转换为规范资源身份。"""
        return ResourceRef(ResourceKey.parse(self.key), self.revision)


class ArtifactReadInput(ArtifactInput):
    """小块字节不会隐式展开成整个文件。"""

    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=4096, ge=1, le=16384)
    encoding: Literal["base64", "utf-8"] = "base64"


class ArtifactPutInput(BaseModel):
    """结构化写入有界；更大内容由宿主使用流式端口保存。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    key: str
    content_base64: str = Field(max_length=_MAX_BASE64)
    media_type: str = "application/octet-stream"


class ArtifactOperation:
    """同一资源能力提供查询与显式写入，不开放任意本机文件路径。"""

    def __init__(self, store: ArtifactStore, action: Literal["stat", "read", "put"]) -> None:
        """从同一输入模型生成操作校验和可选工具入口。"""
        self._store = store
        self._action = action
        self._definition = self.definition_for(action)

    @staticmethod
    def definition_for(action: Literal["stat", "read", "put"]) -> OperationDefinition:
        """在连接内容存储前公开同一份参数和效果定义。"""
        models = {"stat": ArtifactInput, "read": ArtifactReadInput, "put": ArtifactPutInput}
        descriptions = {
            "stat": "核对资源内容版本并读取大小和媒体类型。",
            "read": "按字节位置读取固定资源版本的小块内容。JSON 或文本可指定 encoding=utf-8 直接阅读 text；"
            "默认返回 content_base64 原始字节编码。按 next_offset 继续，has_more 表示正文尚未读完。",
            "put": "保存有界的 base64 内容并返回 SHA256 固定版本；相同版本不会覆盖。",
        }
        kind = "command" if action == "put" else "query"
        tool_name = None if action == "put" else f"aurora:tool/artifact_{action}"
        return OperationDefinition(
            ResourceRef(ResourceKey("aurora", "artifacts", kind, action), "1"),
            descriptions[action],
            models[action].model_json_schema(),
            tool_name,
            True,
        )

    @property
    def definition(self) -> OperationDefinition:
        """返回可发现的版本化操作定义。"""
        return self._definition

    def scopes_for(self, request: OperationRequest) -> ToolScopes:
        """不可变内容没有独立世界线，调用记录由统一路由保存。"""
        return ToolScopes()

    async def execute(self, request: OperationRequest) -> OperationResult:
        """返回实际内容描述和有界字节，不替调用方猜测字符编码。"""
        try:
            return await self._execute(request)
        except ValidationError:
            return OperationResult(status=OperationStatus.FAILED, message="资源参数不符合声明结构")
        except (ValueError, LookupError) as error:
            return OperationResult(status=OperationStatus.FAILED, message=str(error))

    async def _execute(self, request: OperationRequest) -> OperationResult:
        """已确定无有效资源返回时明确报告失败，其他异常交由路由核对。"""
        arguments = thaw_json(request.arguments)
        if self._action == "put":
            write = ArtifactPutInput.model_validate(arguments)
            try:
                content = base64.b64decode(write.content_base64, validate=True)
            except ValueError as error:
                raise ValueError("资源内容不是有效的 base64 编码") from error
            if len(content) > MAX_ARTIFACT_CHUNK:
                raise ValueError("单次写入内容超过字节上限，请使用流式端口")
            info = await self._store.put(ResourceKey.parse(write.key), content, media_type=write.media_type)
            return OperationResult(artifact_data(info))
        if self._action == "read":
            read = ArtifactReadInput.model_validate(arguments)
            chunk = await self._store.read(read.ref, offset=read.offset, limit=read.limit)
            content, next_offset = _chunk_content(chunk, read.encoding)
            return OperationResult(
                {
                    **artifact_data(chunk.info),
                    "offset": chunk.offset,
                    "encoding": read.encoding,
                    **content,
                    "next_offset": next_offset,
                    "has_more": next_offset < chunk.info.size,
                }
            )
        args = ArtifactInput.model_validate(arguments)
        return OperationResult(artifact_data(await self._store.stat(args.ref)))


def _chunk_content(chunk: ArtifactChunk, encoding: Literal["base64", "utf-8"]) -> tuple[dict[str, str], int]:
    """UTF-8 分块只返回完整字符，未完整的尾部字节留给下一次读取。"""
    if encoding == "base64":
        return {"content_base64": base64.b64encode(chunk.content).decode("ascii")}, chunk.next_offset
    decoder = codecs.getincrementaldecoder("utf-8")()
    try:
        text = decoder.decode(chunk.content, final=not chunk.has_more)
    except UnicodeDecodeError as error:
        raise ValueError("资源内容或读取起点不是有效的 UTF-8；请核对位置，二进制内容使用 base64 读取") from error
    pending, _ = decoder.getstate()
    consumed = len(chunk.content) - len(pending)
    if chunk.content and not consumed:
        raise ValueError("读取上限不足以容纳一个 UTF-8 字符，请将 limit 增大至至少 4 字节")
    return {"text": text}, chunk.offset + consumed
