---
order: 4
---

# 节律与记忆

## 各自决定什么

节律决定 Bot 何时获得思考机会，记忆策略帮助选择当前问题相关的经历。目标、行动和未来安排仍由 Bot 判断；必要的恢复状态与证据不会仅因推荐得分低而被丢弃。

两种策略都可以选择规则或学习模型，分别配置。运行时不会自动训练新权重。

## 选择策略

| 配置                            | 规则策略                    | 学习模型                  |
| ------------------------------- | --------------------------- | ------------------------- |
| `rhythm.toml` 的 `policy`       | `aurora:rhythm/model/rules` | `aurora:rhythm/model/gru` |
| `memory_model.toml` 的 `policy` | `aurora:memory/model/rules` | `aurora:memory/model/tgn` |

学习模型通过 `weights` 指定权重文件，或通过 `weights_ref` 指定训练报告中的固定资源版本，二者只能选一项。权重缺失或损坏会报错，不会静默切换策略。修改后校验配置并重启。

## 训练入口

在仓库根目录安装可选依赖，并查看命令帮助：

```bash
uv sync --extra learning
uv run aurora train rhythm --help
uv run aurora train memory --help
```

准备好符合要求的训练与验证 JSONL 后，可分别执行：

```bash
uv run aurora train rhythm train-rhythm.jsonl valid-rhythm.jsonl models/rhythm.pt
uv run aurora train memory train-memory.jsonl valid-memory.jsonl models/memory.pt
```

命令输出训练报告和权重，不覆盖已有输出文件，也不会自动启用新模型。

### 数据准备教程

文档待编写。

训练数据需要有效的效用标注，不能把唤醒频次、曝光量或 Bot 的自评直接当作正确答案。训练与验证应使用独立经历，训练结果的获知时间要早于验证观察，避免把未来信息带入过去的判断。

## 如何判断是否有帮助

固定模型、任务、预算和可读取的数据范围，分别比较规则策略与学习模型的目标结果、推理消耗、延误和重复行动。训练报告提供验证指标，但不能代替实际任务评估。

记忆保存与查询需要存储和计算资源，开销会随保留历史增长。学习模型也不保证比规则策略更适合所有使用场景。
