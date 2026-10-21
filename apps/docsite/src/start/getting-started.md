---
title: 快速开始
order: 1
---

# 快速开始

从源码安装并在终端运行 AuroraBot。

## 前期准备

- Python 3.12
- Git
- [uv](https://docs.astral.sh/uv/)
- [Node.js](https://nodejs.org/) 24 与 [pnpm](https://pnpm.io/) 12

## 克隆仓库

```bash
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
cd AuroraBot
```

也可从 [Releases](https://github.com/AuroraBot-Dev/AuroraBot/releases) 下载源码压缩包并解压。

## 快捷安装

```bash
node scripts/setup.ts
# 也可使用：pnpm run setup
```

按提示安装依赖。个人配置默认暂时跳过，启动时自动补齐；`.env` 默认创建，已存在时默认保留。

## 配置密钥

在 `.env` 中填写所选模型提供方的密钥，默认模型使用：

```dotenv
DEEPSEEK_API_KEY=
```

更多设置见[配置](./configs)。

## 启动 Bot

```bash
aurora start
```

Bot 以默认人格“小光”启动。直接输入消息即可对话；输入 `/help` 查看操作，输入 `/exit` 停止。
