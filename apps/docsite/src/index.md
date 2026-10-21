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
      text: 前端开发
      link: /develop/app-development
---

## AuroraBot 是什么

AuroraBot 是一个为 Agent 提供可以"生活"的运行环境的 Bot 框架。我们想做的不是一个工具一般的 Agent，而是一个能够持续存在、形成自己的节律，并在环境中自主判断和行动的 Bot。

她有自己的人格与状态，可以与人和外部世界建立联系。消息、应用通知和工具结果先成为世界事件，再由她理解和处理。

## 设计哲学

### 以 Bot 为中心设计一切

AuroraBot 把 Bot 当作世界的主体，而不是被调用的接口：她一直存在，拥有自己的人格、状态与边界，一切设计都围绕她的生活展开。这个原则落到架构上有三条：

- **她持续存在，认知是她的经历**：Bot 持有世界日志、目标与记忆。聊天、行动与委派发生在认知执行中；一次执行结束，她仍然存在。
- **一切输入都有媒介**：消息、应用事件、工具结果和到期通知先进入世界，再参与认知。
- **她理解之后才决定**：来自用户的消息不会因为来源就自动成为最高指令。她先理解发生了什么，再决定回应、行动、委派或保持安静；模型只负责理解与判断，外部行动必须经声明的 Tool 执行，结果再作为新事件回到她的世界。
