# Contributing

現在は AgentTree、四 role message、Model/Tool boundary、project composition root の検証を優先します。公共 contract を
変更する前に唯一の RFC を更新し、`contracts ← prompt/ai ← engine ← aurora` の依存方向を維持してください。テストは
fake Model/Tool を使用し、offline かつ deterministic にします。

提出前に `uv run aurora check` を実行してください。
