# Contributing

The current priority is validating AgentTree semantics, four-role messages, model/tool boundaries, and the project
composition root. Update the authoritative RFC before changing public semantics, preserve the dependency direction
`contracts ← prompt/ai ← engine ← aurora`, and keep tests offline and deterministic with fake Models and Tools.

Run `uv run aurora check` before submitting changes.
