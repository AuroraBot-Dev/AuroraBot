# 贡献指南

<b>中文</b> | <a href="./CONTRIBUTING.en.md">English</a> | <a href="./CONTRIBUTING.ja.md">日本語</a>

感谢你对 AuroraBot 的关注！这份指南会帮助你快速把项目跑起来，并说明推荐的贡献流程。

## 环境要求

- **Python** ≥ 3.12, < 3.13
- **uv**（包管理器）— [安装指南](https://docs.astral.sh/uv/getting-started/installation/)

## 把项目跑起来

```bash
# 1. 克隆仓库
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
cd AuroraBot

# 2. 安装依赖（含开发工具）
uv sync --group dev

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，填入必需的 API Key 等配置

# 4. 启动
uv run python bot.py
```

## 开发工具

| 命令                             | 用途                            |
| -------------------------------- | ------------------------------- |
| `uv run pytest --cov=src`        | 运行测试并统计覆盖率            |
| `uv run ruff check src/ tests/`  | 代码检查                        |
| `uv run ruff format src/ tests/` | 代码格式化                      |
| `uv run pyright src/`            | 类型检查（默认不检查 `tests/`） |

> 建议在提交 PR 前至少运行 `uv run pytest --cov=src`、`uv run ruff check src/ tests/` 和 `uv run pyright src/`。CI 流水线会执行带覆盖率的 `pytest`、`ruff check`、`ruff format --check` 与 `pyright src/`，确保代码风格一致、类型检查稳定且没有明显回归。

## 贡献流程

我们采用**分支 → PR → 合并即废弃**的轻量流程：

```
dev（最新）
  │
  ├── feat/xxx          ← 新功能分支
  ├── fix/xxx           ← 修复分支
  └── refact/xxx        ← 重构或优化代码分支
```

### 1. 从最新的 `dev` 分支切出

```bash
git checkout dev
git pull origin dev
git checkout -b feat/my-feature    # 或 fix/xxx, refact/xxx
```

> 分支前缀说明：
>
> - **feat/** — 新功能
> - **fix/** — Bug 修复
> - **refact/** — 代码重构或优化（不改变外部行为）

### 2. 在分支上完成开发

在本地分支上自由提交、修改。保持提交信息清晰即可。

### 3. 向 `dev` 分支提交 PR

开发完成后，将你的分支推送到远端，并向 `dev` 分支发起 Pull Request。

### 4. PR 合并后，分支使命结束

PR 合并到 `dev` 后，该分支的使命就完成了。**原则上不再使用该分支继续开发新功能。** 你可以放心删除它：

```bash
git branch -d feat/my-feature
```

### 5. 如果还需要修改

有两种方式：

- **PR 尚未合并** — 将 PR 标记为 **Draft**，继续在同一个分支上修改，完成后改回 Ready for review。
- **PR 已合并** — 重复以上流程，从最新的 `dev` 切出新的 `feat/`、`fix/` 或 `refact/` 分支。

> 这样做的好处是每个分支职责单一、生命周期清晰，不会出现一个分支反复承载多个不相关改动的混乱情况。

---

如有任何疑问，欢迎在 [Issues](https://github.com/AuroraBot-Dev/AuroraBot/issues) 中提出。
