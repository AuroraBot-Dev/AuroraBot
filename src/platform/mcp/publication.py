"""RFC 0016 MCP Publication validation, dispatch, idempotency, and recovery."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from src.localhost.ports import PublicationExecutionRequest, PublicationOutcome

if TYPE_CHECKING:
    from src.contracts.configuration import AppConfig, AppDestinationConfig, AppPublicationConfig, AuroraConfig
    from src.platform.mcp.publication_ledger import MCPPublicationLedger, PublicationRecord

ToolCaller = Callable[[str, dict[str, object]], Awaitable[dict[str, object]]]


class MCPPublicationService:
    """Execute canonical raw publication tools against one immutable private App snapshot."""

    def __init__(self, configuration: AuroraConfig, ledger: MCPPublicationLedger, call_tool: ToolCaller) -> None:
        self._configuration = configuration
        self._ledger = ledger
        self._call_tool = call_tool
        self._bindings = {
            publication.capability: (app, publication)
            for app in configuration.apps
            if app.kind == "communication"
            for publication in app.publications
        }

    async def execute(self, request: PublicationExecutionRequest) -> PublicationOutcome:
        binding = self._bindings.get(request.capability)
        if binding is None:
            return _failed("MCP Publication rejected", f"unknown publication capability: {request.capability}")
        app, publication = binding
        arguments, error = self._canonical_arguments(request, app, publication)
        digest = _request_digest(arguments if arguments is not None else asdict(request))
        state, existing = self._ledger.record_started(
            request.request_id,
            digest,
            app.package,
            request.capability,
            publication.tool,
        )
        if state == "conflict":
            return _failed("MCP Publication rejected", "delivery_id was reused with a different request")
        if state == "existing":
            assert existing is not None
            return _record_outcome(existing)
        if error is not None or arguments is None:
            detail = error or "invalid canonical publication request"
            self._ledger.record_failed(request.request_id, "MCP Publication rejected", detail)
            return _failed("MCP Publication rejected", detail)
        try:
            result = await self._call_tool(publication.tool, arguments)
        except Exception as dispatch_error:
            return PublicationOutcome(
                "delivery_unknown",
                "MCP Publication delivery is unknown",
                error=f"{type(dispatch_error).__name__}: {dispatch_error}",
            )
        if result.get("is_error") is True:
            detail = str(result.get("text") or result.get("content") or "MCP tool returned isError")
            self._ledger.record_failed(request.request_id, "MCP Publication failed", detail)
            return _failed("MCP Publication failed", detail)
        accepted = _accepted_result(result, request.request_id)
        if accepted is None:
            return PublicationOutcome(
                "delivery_unknown",
                "MCP Publication returned an invalid result",
                error="invalid canonical accepted result",
            )
        external_message_id = accepted["external_message_id"]
        try:
            self._ledger.record_accepted(request.request_id, "MCP Publication accepted", external_message_id)
        except Exception as ledger_error:
            return PublicationOutcome(
                "delivery_unknown",
                "MCP Publication delivery is unknown",
                error=f"ledger rejected accepted result: {type(ledger_error).__name__}",
            )
        return PublicationOutcome(
            "accepted",
            "MCP Publication accepted",
            external_message_id=external_message_id,
        )

    async def recover(self, request: PublicationExecutionRequest) -> PublicationOutcome:
        record = self._ledger.get(request.request_id)
        if record is None:
            return _failed("MCP Publication was interrupted before dispatch", "interrupted_before_dispatch")
        expected = self._expected_digest(request)
        if expected is not None and expected != record.request_digest:
            return _failed("MCP Publication recovery rejected", "delivery_id request digest mismatch")
        return _record_outcome(record)

    def _expected_digest(self, request: PublicationExecutionRequest) -> str | None:
        binding = self._bindings.get(request.capability)
        if binding is None:
            return None
        arguments, _error = self._canonical_arguments(request, *binding)
        return _request_digest(arguments if arguments is not None else asdict(request))

    def _canonical_arguments(
        self,
        request: PublicationExecutionRequest,
        app: AppConfig,
        publication: AppPublicationConfig,
    ) -> tuple[dict[str, object] | None, str | None]:
        if request.configuration_hash != self._configuration.apps_configuration_hash:
            return None, "apps configuration hash mismatch"
        if request.endpoint_id != app.package or request.operation != publication.operation:
            return None, "publication binding does not match endpoint or operation"
        if not request.text:
            return None, "publication text must be non-empty"
        address_ref: str | None = None
        if request.operation == "reply":
            if not request.route_ref or request.destination is not None or request.hop_count != 0:
                return None, "reply requires only a route_ref and zero hops"
        else:
            destination = self._destination(request, app)
            if destination is None:
                return None, "publication destination alias or binding is invalid"
            if destination.target_audience_ref != request.target_audience_ref:
                return None, "publication target audience does not match destination"
            if not _source_allowed(destination.allowed_source_audiences, request.source_audience_ref):
                return None, "publication source audience is not allowed"
            expected_hops = 1 if request.operation == "relay" else 0
            if (
                request.hop_count != expected_hops
                or request.hop_count > self._configuration.communication.relay_hop_limit
            ):
                return None, "publication hop count is invalid"
            if request.route_ref is not None:
                return None, "relay and proactive_send forbid route_ref"
            address_ref = destination.address_ref
        return {
            "operation": request.operation,
            "route_ref": request.route_ref,
            "address_ref": address_ref,
            "text": request.text,
            "delivery_id": request.request_id,
            "provenance": {
                "source_endpoint_id": request.source_endpoint_id,
                "source_external_event_id": request.source_external_event_id,
                "source_audience_ref": request.source_audience_ref,
                "destination_endpoint_id": request.endpoint_id,
                "target_audience_ref": request.target_audience_ref,
                "hop_count": request.hop_count,
            },
        }, None

    @staticmethod
    def _destination(request: PublicationExecutionRequest, app: AppConfig) -> AppDestinationConfig | None:
        return next(
            (
                destination
                for destination in app.destinations
                if destination.alias == request.destination and destination.capability == request.capability
            ),
            None,
        )


def _source_allowed(patterns: tuple[str, ...], audience_ref: str) -> bool:
    return any(
        pattern in {"*", audience_ref} or (pattern.endswith(":*") and audience_ref.startswith(pattern[:-1]))
        for pattern in patterns
    )


def _request_digest(arguments: dict[str, Any]) -> str:
    canonical = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _accepted_result(result: dict[str, object], request_id: str) -> dict[str, str] | None:
    candidate: object = result
    structured = result.get("structured_content")
    if isinstance(structured, dict):
        candidate = structured
    elif set(result) != {"status", "delivery_id", "external_message_id"}:
        content = result.get("content")
        if isinstance(content, list) and len(content) == 1 and isinstance(content[0], dict):
            text = content[0].get("text")
            if isinstance(text, str):
                try:
                    candidate = json.loads(text)
                except json.JSONDecodeError:
                    return None
    if not isinstance(candidate, dict) or set(candidate) != {"status", "delivery_id", "external_message_id"}:
        return None
    delivery_id = candidate.get("delivery_id")
    external_message_id = candidate.get("external_message_id")
    if candidate.get("status") != "accepted" or delivery_id != request_id:
        return None
    if not isinstance(external_message_id, str) or not external_message_id:
        return None
    return {"external_message_id": external_message_id}


def _record_outcome(record: PublicationRecord) -> PublicationOutcome:
    if record.status == "ACCEPTED" and record.external_message_id is not None:
        return PublicationOutcome(
            "accepted",
            record.summary or "MCP Publication accepted",
            external_message_id=record.external_message_id,
        )
    if record.status == "FAILED":
        return _failed(record.summary or "MCP Publication failed", record.error or "publication failed")
    return PublicationOutcome(
        "delivery_unknown",
        "MCP Publication delivery is unknown",
        error="dispatch_started_without_terminal_outcome",
    )


def _failed(summary: str, error: str) -> PublicationOutcome:
    return PublicationOutcome("failed", summary, error=error)
