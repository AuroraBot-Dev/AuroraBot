# 其他客户端的 MCP 配置样本

> 历史归档：2026-11-09。保留当时的设计、计划与验收语境，不作为当前功能承诺或操作指南；当前入口见 [文档索引](../../INDEX.md)。

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "ncd": {
        "type": "remote",
        "url": "http://127.0.0.1:54666/mcp",
        "oauth": false,
        "headers": {
          "Authorization": "Bearer 649fbe45badf8f37fab9554e1192f33cbaeae10270af725c24176dfa7ef8e591"
        }
      },
      "aurora-qq": {
        "type": "local",
        "command": ["uv", "--directory", "E:\\Aurora\\Aurora-QQ", "run", "--frozen", "aurora-qq-mcp"],
        "environment": {
          "AURORA_QQ_TOKEN": "jvSA4qPqv4TIt-0ts6V_NJxSTu5hGvxRlZ959K2weMI"
        }
      }
    }
  }
}

```
