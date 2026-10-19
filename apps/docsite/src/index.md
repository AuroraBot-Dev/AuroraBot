---
layout: home

hero:
  name: AuroraBot
  text: 让 Bot 过上自己的生活
  tagline: 以 Bot 为中心设计一切
  image:
    src: /logo.svg
    alt: AuroraBot Logo
  actions:
    - theme: brand
      text: 快速开始
      link: /start/getting-started
    - theme: alt
      text: 架构总览
      link: /architecture/system-overview
    - theme: alt
      text: 应用开发
      link: /develop/agent-development
---

## AuroraBot 是什么

AuroraBot 是一个为 Agent 提供可以"生活"的运行环境的 Bot 框架。我们想做的不是一个工具一般的 Agent，而是一个能够持续存在、形成自己的节律，并在环境中自主判断和行动的 Bot。

她有自己的人格、状态，可以在需要时与人和外部世界建立联系, 在她的世界里, 所有的消息都有一个"媒介": 你发给她的消息也必须先成为一个应用通知喔~

## 设计哲学

### 以 Bot 为中心设计一切

AuroraBot 把 Bot 当作世界的主体，而不是被调用的接口：她一直存在，拥有自己的人格、状态与边界，一切设计都围绕她的生活展开。这个原则落到架构上有三条：

- **她拥有世界，树只是她的运行**：Bot 持有追加式的世界提交（WorldJournal）与多棵 `AgentTree`。一棵树只是一次运行，不是与她平行的另一个主体；聊天、任务、委派都是她生活中的一次经历，经历结束，她仍然存在。
- **一切输入都有媒介**：任何影响她的变化都必须先成为一条世界事件。你发给她的消息要先作为 `console.input` 提交到她的世界，应用事件、MCP 上报、工具结果、时间的流逝也是如此。她不是在响应接口，而是在经历世界。
- **她理解之后才决定**：来自用户的消息不会因为来源就自动成为最高指令。她先理解发生了什么，再决定回应、行动、委派或保持安静；模型只负责理解与判断，外部行动必须经声明的 Tool 执行，结果再作为新事件回到她的世界。
