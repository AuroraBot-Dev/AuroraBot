"""RFC 0015 Publication authorization and persisted lease projections."""

# ruff: noqa: TRY003

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from jsonschema import ValidationError, validate

from src.contracts.agent import (
    ActivityRequest,
    AgentInstance,
    AgentProfile,
    CapabilityCatalogSnapshot,
    CapabilityDescriptor,
    CommunicationContext,
    DestinationGrant,
    PublicationCompletionMode,
    PublicationLease,
    PublicationOperation,
    PublicationRequest,
    TaskState,
)


class PublicationContractError(ValueError):
    """Publication metadata or capability contract is invalid."""


class PublicationAuthorizationError(PermissionError):
    """A Publication request is outside the Agent's effective grants."""


def communication_ingress(
    *,
    event_type: str,
    data: dict[str, Any],
    catalog: CapabilityCatalogSnapshot,
    profile: AgentProfile,
    reply_route_ttl_seconds: float,
) -> tuple[str, dict[str, str] | None]:
    raw = data.get("communication")
    if raw is None:
        return "system.local", None
    communication = CommunicationContext.from_dict(raw, require_message_fields=event_type == "message.received")
    if communication.reply_route_ref is None:
        return communication.audience_ref, None
    matches = [
        descriptor
        for descriptor in catalog.capabilities
        if descriptor.kind == "publication"
        and descriptor.operation == "reply"
        and descriptor.endpoint == communication.endpoint_id
        and descriptor.id in profile.capabilities
    ]
    if len(matches) != 1:
        raise PublicationContractError("communication reply route must resolve to exactly one active capability")
    expires_at = (datetime.now(UTC) + timedelta(seconds=reply_route_ttl_seconds)).isoformat()
    return communication.audience_ref, {
        "endpoint_id": communication.endpoint_id,
        "route_ref": communication.reply_route_ref,
        "capability_id": matches[0].id,
        "expires_at": expires_at,
    }


def validate_destination_grants(grants: tuple[DestinationGrant, ...]) -> dict[str, DestinationGrant]:
    result: dict[str, DestinationGrant] = {}
    for grant in grants:
        if not grant.alias or grant.alias in result:
            raise PublicationContractError("destination grant aliases must be non-empty and unique")
        if grant.operation not in {"relay", "proactive_send"}:
            raise PublicationContractError("destination grant operation must be relay or proactive_send")
        if not all((grant.endpoint_id, grant.capability_id, grant.target_audience_ref, grant.configuration_hash)):
            raise PublicationContractError("destination grant fields must be non-empty")
        result[grant.alias] = grant
    return result


def effective_descriptors(  # noqa: PLR0913
    *,
    profile: AgentProfile,
    catalog: CapabilityCatalogSnapshot,
    agent: AgentInstance,
    task: TaskState,
    reply_capability_ids: frozenset[str],
    destination_grants: dict[str, DestinationGrant],
) -> tuple[CapabilityDescriptor, ...]:
    descriptors = []
    for capability in sorted(profile.capabilities):
        descriptor = catalog.by_id.get(capability)
        if descriptor is None:
            continue
        if descriptor.kind == "effect":
            if agent.parent_agent_id is None or (descriptor.result_mode != "terminal" and not descriptor.root_only):
                descriptors.append(descriptor)
            continue
        if agent.parent_agent_id is not None or not descriptor.root_only:
            continue
        if descriptor.operation == "reply" and descriptor.id in reply_capability_ids:
            descriptors.append(descriptor)
            continue
        aliases = sorted(
            grant.alias
            for grant in destination_grants.values()
            if grant.capability_id == descriptor.id
            and grant.endpoint_id == descriptor.endpoint
            and grant.operation == descriptor.operation
            and source_allowed(grant, task.audience_ref)
        )
        if aliases:
            descriptors.append(replace(descriptor, parameters_schema=_destination_tool_schema(descriptor, aliases)))
    return tuple(descriptors)


def authorize_publication(  # noqa: C901, PLR0913
    *,
    publication: PublicationRequest,
    task: TaskState,
    agent: AgentInstance,
    profile: AgentProfile,
    catalog: CapabilityCatalogSnapshot,
    reply_grant: dict[str, str] | None,
    destination_grants: dict[str, DestinationGrant],
    root_amp: dict[str, Any] | None,
    configuration_hash: str,
) -> dict[str, Any]:
    if agent.parent_agent_id is not None:
        raise PublicationAuthorizationError("only the root Agent may request Publication")
    target_audience: str
    if publication.operation == "reply":
        if reply_grant is None:
            raise PublicationAuthorizationError("publication reply route is unavailable or expired")
        capability_id = reply_grant["capability_id"]
        endpoint_id = reply_grant["endpoint_id"]
        target_audience = reply_grant["audience_ref"]
    else:
        grant = destination_grants.get(publication.destination or "")
        if grant is None:
            raise PublicationAuthorizationError("publication destination grant is unavailable")
        if grant.operation != publication.operation or not source_allowed(grant, task.audience_ref):
            raise PublicationAuthorizationError(
                "publication destination does not allow this operation or source audience"
            )
        if grant.configuration_hash != configuration_hash:
            raise PublicationAuthorizationError("publication destination configuration hash is stale")
        capability_id = grant.capability_id
        endpoint_id = grant.endpoint_id
        target_audience = grant.target_audience_ref
    if capability_id not in profile.capabilities:
        raise PublicationAuthorizationError(f"Agent profile {profile.id} cannot request {capability_id}")
    descriptor = catalog.by_id.get(capability_id)
    if descriptor is None or descriptor.kind != "publication":
        raise PublicationContractError(f"unknown publication capability {capability_id}")
    if not descriptor.root_only or descriptor.endpoint != endpoint_id or descriptor.operation != publication.operation:
        raise PublicationAuthorizationError("publication capability does not match its grant")
    parameters = {key: value for key, value in publication.to_dict().items() if value is not None}
    schema_properties = descriptor.parameters_schema.get("properties")
    if isinstance(schema_properties, dict):
        parameters = {key: value for key, value in parameters.items() if key in schema_properties}
    try:
        validate(parameters, descriptor.parameters_schema)
    except ValidationError as error:
        raise PublicationContractError(
            f"publication parameters do not match {capability_id}: {error.message}"
        ) from error
    source_endpoint, source_event = _source_provenance(root_amp)
    return {
        "kind": "publication",
        "summary": f"publication.requested:{capability_id}",
        "request": {
            **publication.to_dict(),
            "capability": capability_id,
            "endpoint_id": endpoint_id,
            "source_audience_ref": task.audience_ref,
            "target_audience_ref": target_audience,
            "source_endpoint_id": source_endpoint,
            "source_external_event_id": source_event,
            "root_message_id": task.root_message_id,
            "hop_count": 1 if publication.operation == "relay" else 0,
            "configuration_hash": configuration_hash,
        },
    }


def publication_lease(activity: ActivityRequest) -> PublicationLease:
    request = activity.request
    return PublicationLease(
        activity_id=activity.activity_id,
        task_id=activity.task_id,
        agent_id=activity.agent_id,
        request_id=activity.idempotency_key,
        capability=str(request["capability"]),
        endpoint_id=str(request["endpoint_id"]),
        operation=cast("PublicationOperation", request["operation"]),
        text=str(request["text"]),
        completion_mode=cast("PublicationCompletionMode", request["completion_mode"]),
        source_audience_ref=str(request["source_audience_ref"]),
        target_audience_ref=str(request["target_audience_ref"]),
        root_message_id=str(request["root_message_id"]),
        route_ref=request.get("route_ref"),
        destination=request.get("destination"),
        reason=request.get("reason"),
        tool_call_id=request.get("tool_call_id"),
        continuation=request.get("continuation"),
        source_endpoint_id=request.get("source_endpoint_id"),
        source_external_event_id=request.get("source_external_event_id"),
        hop_count=int(request.get("hop_count", 0)),
        configuration_hash=str(request.get("configuration_hash", "")),
    )


def source_allowed(grant: DestinationGrant, audience_ref: str) -> bool:
    return any(
        pattern in {"*", audience_ref} or (pattern.endswith(":*") and audience_ref.startswith(pattern[:-1]))
        for pattern in grant.allowed_source_audiences
    )


def _destination_tool_schema(descriptor: CapabilityDescriptor, aliases: list[str]) -> dict[str, Any]:
    configured = descriptor.parameters_schema.get("properties")
    configured_properties = configured if isinstance(configured, dict) else {}
    properties: dict[str, Any] = {
        "text": configured_properties.get("text", {"type": "string", "minLength": 1}),
        "destination": {
            "type": "string",
            "enum": aliases,
            "description": "Choose one authorized destination alias.",
        },
    }
    required = ["text", "destination"]
    if descriptor.operation == "proactive_send":
        properties["reason"] = configured_properties.get("reason", {"type": "string", "minLength": 1})
        required.append("reason")
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _source_provenance(root_amp: dict[str, Any] | None) -> tuple[str | None, str | None]:
    if root_amp is None:
        return None, None
    payload = root_amp.get("payload")
    data = payload.get("data") if isinstance(payload, dict) else None
    raw = data.get("communication") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return None, None
    endpoint = raw.get("endpoint_id")
    event_id = raw.get("external_event_id")
    return (endpoint if isinstance(endpoint, str) else None, event_id if isinstance(event_id, str) else None)
