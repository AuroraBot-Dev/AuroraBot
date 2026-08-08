# 0215：AI 包外部接口——get_response、词嵌入、模态与统计

状态：已接受
日期：2026-08-07
来源：ai 包功能规格（litellm 集中管理、models.dev 模态、定价、脱壳输出、统计、client 导出）
先决条件：RFC 0212/0213/0214（角色域自洽）

## 问题

ai 包已满足"litellm 集中 provider + models.dev 定价"，但缺外部使用面：

1. 外部库（mem0 等）需要一个**简单入口**：传入 role 与 inputs，拿到脱壳的纯粹输出。
2. **词嵌入**没有角色与通道（第四类基础角色）。
3. models.dev 的**输入/输出模态**数据已在缓存但未暴露查询。
4. `GenerationTask` 的生成打断（取消）路径冗余；完成调用的**总费用与分类统计**无查询接口。
5. 无法**导出 OpenAI 兼容 client** 给外部库。

## 决定

### 1. `get_response(role, inputs)` —— 脱壳输出

```python
async def get_response(self, role: str, inputs: list[dict]) -> dict[str, Any]:
```

- `inputs`：OpenAI 风格消息数组（`[{"role": "user", "content": "..."}]`）；embedding 角色时是文本数组。
- 返回**脱壳 dict**（去掉 litellm/ModelResult 包装）：
  - chat 类角色：`{"text": str, "tool_calls": [...], "finish_reason": str}`
  - embedding 角色：`{"embeddings": [[float, ...], ...], "model": str}`
- 内部按 `handler.embed` 是否存在分派（接口统一，语义分离）。

### 2. EmbeddingRole（第四类基础角色）

- `roles/embedding.py`：`EmbeddingRole(RoleHandler)`，`endpoint = "embeddings"`，`capability_baseline = {"embedding"}`。
- 实现 `embed(gateway, inputs: list[str]) -> list[list[float]]`（`litellm.aembedding`）。
- `RoleHandler` 增加可选 `embed` 方法（默认不实现）。
- `models.toml` 增加 `[models.roles.embedding]`（provider + model）。

### 3. 模态持有与查询

- `models.py` 增加 `get_modalities_by_id(model_id) -> tuple[frozenset, frozenset]`（输入/输出模态，来自 models.dev 原始缓存）。
- `gateway.modalities_for(role) -> tuple[frozenset, frozenset]`：角色绑定模型的输入/输出模态（供角色校验输入模态、外部查询）。

### 4. 移除生成打断，追踪总费用

- `ChatCaller._stream_and_collect` 删除取消分支（`is_cancelled`/CancelledError 传播），流式收集恒完整。
- `CostTracker` 增加分类统计：`total_cost()`、`by_role()`、`by_model()`、`by_status()`（现有 `add`/`summary` 保留）。
- **费用持久化**：与 engine/memory/ops 同一持久化体系（RFC 0217 §5）——`CostStore`
  （`src/ai/cost_store.py`）以 SQLAlchemy ORM 声明 `cost_records` 表，落
  `data/ai/cost.sqlite3`（WAL，`schema_meta` 版本号经 `utils.migration.initialize_storage`
  统一初始化，迁移序列见 `src/ai/migration/`，当前 v1，只追加无更新路径）；
  `CostTracker` 启动时从库恢复历史到内存缓存，`add` 同步写库，统计接口保持内存查询
  （存储镜像：src/ai → `storage.ai`）。

### 5. `export_openai_client()`

- `gateway.export_openai_client() -> litellm.OpenAI`：导出 litellm 的 OpenAI 兼容 client（mem0 等库直接使用）。

## 结果

- 外部使用方式收敛：`get_response("<role>", <inputs>)` 返回脱壳输出；embedding 同入口。
- 四类基础角色齐全：快速 / 质量 / 多模态 / 词嵌入。
- 模态、费用、分类数据全部可查询；client 可导出。

## 兼容性

- 对外契约：`ModelRequest`/`ModelResult` 不变；`complete()` 保留（engine 继续使用）。
- 配置：`models.toml` 新增 embedding role（可选，缺省时该角色不可用——resolve 报错）。
- 测试：get_response 脱壳、embedding 通道、模态查询、费用统计、client 导出用例。
