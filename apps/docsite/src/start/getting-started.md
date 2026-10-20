---
title: 快速开始
order: 1
---

# 快速开始

::: info
此版本暂时只支持从源码运行. 后期会提供一键包安装.
:::

## 前期准备

- Python 3.12+
- Git
- [uv](https://docs.astral.sh/uv/)

## 克隆仓库

```bash
git clone https://github.com/AuroraBot-Dev/AuroraBot.git
cd AuroraBot
```

::: tip
或者你可以通过 [Releases](https://github.com/AuroraBot-Dev/AuroraBot/releases) 下载最新稳定版本的源码压缩包, 并解压到 `AuroraBot` 目录下.
:::

## 快捷安装

```bash
./scripts/linux/setup.sh
# macOS: ./scripts/macos/setup.command;
# Windows: .\scripts\windows\setup.ps1.
```

`setup.sh` 会检查 git/uv/pnpm，询问是否将 aurora 全局链接到用户工具目录，然后由 `aurora setup` 完成依赖同步、个人配置以及 应用工作区依赖安装。

::: warning
我们正在调查 Windows 平台的 ps1 脚本运行出错的问题. 初步证据证明该问题由文件编码与控制台编码不一致引起.
一个可能的修复方案为: 在运行脚本前, 使用对应的编码配置命令, 将控制台编码设置为 `UTF-8`
:::

## 配置密钥

::: tip
在 `.env` 中配置你的密钥:

```
DEEPSEEK_API_KEY=
# XIAOMI_MIMO_API_KEY=
# OPENAI_API_KEY=
# SILICONFLOW_API_KEY=
```

更多配置说明见 [配置](./configs)
:::

## 启动Bot

```bash
aurora start
```

此时你的Bot将会以默认人格`小光`启动，直接输入消息即可对话；输入 `/help` 查看操作，输入 `/exit` 停止。
