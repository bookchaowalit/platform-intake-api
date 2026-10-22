"""Shared helpers for the intake domain tests: paths and minimal valid bodies."""

import uuid
from typing import Any

SOURCES = "/v1/sources"
INTAKES = "/v1/intakes"
EVENTS = "/v1/intake-events"


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def create_source(client: Any, owner: dict[str, str], **fields: Any) -> Any:
    body = {
        "source_key": unique("src"),
        "display_name": "Bank statements",
        "source_kind": "file",
        "domain": "finance",
        "dataset": "statements",
        **fields,
    }
    return client.post(SOURCES, headers=owner, json=body)


def create_intake(
    client: Any, owner: dict[str, str], source_id: int, **fields: Any
) -> Any:
    body = {
        "intake_key": unique("in"),
        "source_id": source_id,
        "domain": "finance",
        "dataset": "statements",
        "payload_kind": "csv",
        "input_ref": "inbox/2026-10/statement.csv",
        "idempotency_key": unique("idem"),
        **fields,
    }
    return client.post(INTAKES, headers=owner, json=body)


def create_event(
    client: Any, owner: dict[str, str], intake_id: int, **fields: Any
) -> Any:
    body = {
        "intake_id": intake_id,
        "event_type": "claimed",
        "to_status": "processing",
        **fields,
    }
    return client.post(EVENTS, headers=owner, json=body)


def source_id(client: Any, owner: dict[str, str], **fields: Any) -> int:
    response = create_source(client, owner, **fields)
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def intake_id(client: Any, owner: dict[str, str], **fields: Any) -> int:
    response = create_intake(client, owner, source_id(client, owner), **fields)
    assert response.status_code == 201, response.text
    return int(response.json()["id"])
