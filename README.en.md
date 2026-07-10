# AuroraBot vNext

<p align="center">
  <a href="README.md">中文</a> | <b>English</b> | <a href="README.ja.md">日本語</a>
</p>

AuroraBot is being rebuilt as an autonomous-agent framework centred on causal events. The repository is in its rebuild phase: the former implementation is frozen in `legacy/` and is not the source of truth for vNext.

## Source of truth

`docs/rfc/` is the sole architectural baseline for vNext. Code, configuration examples, contribution guidance, and public documentation must follow accepted RFCs.

The first closed loop is:

```text
Platform environment event (AMP JSON)
  → Kernel intake, cycle snapshot, and graph scheduling
  → builtin.decide node
  → effect.requested
  → platform capability execution
  → effect.succeeded / effect.failed (next cycle)
```

Generated text is not an effect. The loop closes only when the platform reports an execution outcome.

## Layout

```text
config/       TOML configuration and profile overrides
docs/rfc/     Normative vNext design documents
legacy/       Frozen former code and tests; migration reference only
src/          vNext implementation
tests/        vNext contract and integration tests
extensions/   Recommended location for third-party extensions
```

The managed kernel workspace is `data/kernel/{inbox,process,archive}`. TOML describes structure, JSON carries runtime data, and secrets come from environment variables.

## RFCs

- [RFC 0000: RFC process](docs/rfc/0000-rfc-process.md)
- [RFC 0001: Architecture baseline](docs/rfc/0001-architecture.md)
- [RFC 0002: Configuration baseline](docs/rfc/0002-configuration.md)
- [RFC 0003: Event and causality contract](docs/rfc/0003-event-contract.md)
- [RFC 0004: Extension contract](docs/rfc/0004-plugin-contract.md)
- [RFC 0005: Model gateway](docs/rfc/0005-model-gateway.md)

## Rebuild status

vNext does not yet expose a runnable Bot entry point. Do not treat the root legacy entry point or code in `legacy/` as the vNext launch path.

## License

Licensed under [Apache License 2.0](LICENSE).
