# ruff: noqa: TC003, TRY003, TRY004, TRY301
"""Managed event workspace visible to operators and external producers."""

from __future__ import annotations

import json
from pathlib import Path
from shutil import move

from src.kernel.models import CognitiveEvent


class CognitiveWorkspace:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.external_inbox = root / "inbox" / "external"
        self.inbox = root / "inbox" / "pending"
        self.outbox_candidate = root / "outbox" / "candidate"
        self.outbox_published = root / "outbox" / "published"
        self.archive = root / "archive"
        for path in (
            self.external_inbox,
            self.inbox,
            self.outbox_candidate,
            self.outbox_published,
            self.archive,
            root / ".aurora",
        ):
            path.mkdir(parents=True, exist_ok=True)

    def write_ingress(self, event: CognitiveEvent) -> None:
        self._write(self.inbox / f"{event.event_id}.json", event)

    def write_outbox(self, event: CognitiveEvent) -> None:
        target = self.outbox_published if event.event_type == "output.published" else self.outbox_candidate
        self._write(target / f"{event.event_id}.json", event)

    def scan_external(self) -> list[CognitiveEvent]:
        events: list[CognitiveEvent] = []
        for path in sorted(self.external_inbox.rglob("*.json")):
            if path.name.endswith(".part.json"):
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8-sig"))
                if not isinstance(raw, dict):
                    raise ValueError("external event must be an object")
                payload = raw.get("payload", raw)
                if not isinstance(payload, dict):
                    raise ValueError("external payload must be an object")
                events.append(
                    CognitiveEvent.create(
                        "input.external",
                        payload,
                        source=str(raw.get("source", "filesystem")),
                        session_id=str(raw.get("session_id", "filesystem")),
                        tags={
                            "transport": "workspace",
                            "workspace_path": path.relative_to(self.external_inbox).as_posix(),
                        },
                    )
                )
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            archived = self.archive / "external" / path.relative_to(self.external_inbox)
            archived.parent.mkdir(parents=True, exist_ok=True)
            move(str(path), str(archived))
        return events

    @staticmethod
    def _write(path: Path, event: CognitiveEvent) -> None:
        payload = {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "source": event.source,
            "session_id": event.session_id,
            "episode_id": event.episode_id,
            "causation_id": event.causation_id,
            "created_at": event.created_at.isoformat(),
            "tags": event.tags,
            "payload": event.payload,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
