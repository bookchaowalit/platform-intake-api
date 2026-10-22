"""Defaults on create, unique keys, imports and what a reference protects."""

import uuid

from intake_helpers import (
    INTAKES,
    SOURCES,
    create_event,
    create_intake,
    create_source,
    intake_id,
    source_id,
)


def test_new_source_is_planned_private_manual_and_owned_by_solo_empire(client, owner):
    response = create_source(client, owner)
    assert response.status_code == 201, response.text
    source = response.json()
    assert source["status"] == "planned"
    assert source["privacy_class"] == "private"
    assert source["ingest_mode"] == "manual"
    assert source["owner_scope"] == "solo_empire"
    assert source["retention_class"] == "operational"
    assert source["last_ingested_at"] is None
    assert source["version"] == 1


def test_new_intake_is_queued_by_a_human_with_no_attempts(client, owner):
    intake = create_intake(client, owner, source_id(client, owner)).json()
    assert intake["status"] == "queued"
    assert intake["requested_by"] == "human"
    assert intake["attempt_count"] == 0
    assert intake["record_count"] is None
    assert intake["schema_version"] == "1"
    assert intake["privacy_class"] == "private"
    assert intake["retention_class"] == "operational"
    assert intake["lease_owner"] is None


def test_new_event_is_attributed_to_the_system(client, owner):
    event = create_event(client, owner, intake_id(client, owner)).json()
    assert event["actor"] == "system"
    assert event["from_status"] is None


def test_source_key_is_unique_within_a_workspace(client, owner, harness, platform):
    assert create_source(client, owner, source_key="bank-kbank").status_code == 201
    again = create_source(client, owner, source_key="bank-kbank")
    assert again.status_code == 409, again.text
    assert again.json()["detail"] == {"error": "conflict"}
    stranger_actor = uuid.uuid4()
    platform.grants[stranger_actor] = set(harness.cell.permissions())
    stranger = harness.token(stranger_actor, uuid.uuid4())
    assert create_source(client, stranger, source_key="bank-kbank").status_code == 201


def test_intake_key_is_unique(client, owner):
    src = source_id(client, owner)
    assert (
        create_intake(client, owner, src, intake_key="2026-10-22-a").status_code == 201
    )
    assert (
        create_intake(client, owner, src, intake_key="2026-10-22-a").status_code == 409
    )


def test_the_same_payload_cannot_be_queued_twice(client, owner):
    src = source_id(client, owner)
    first = create_intake(client, owner, src, idempotency_key="sha-abc")
    assert first.status_code == 201, first.text
    duplicate = create_intake(client, owner, src, idempotency_key="sha-abc")
    assert duplicate.status_code == 409, duplicate.text
    listed = client.get(INTAKES, headers=owner, params={"idempotency_key": "sha-abc"})
    assert len(listed.json()["items"]) == 1


def test_renaming_a_source_to_a_taken_key_is_refused(client, owner):
    create_source(client, owner, source_key="taken")
    other = create_source(client, owner, source_key="free").json()
    path = f"{SOURCES}/{other['id']}"
    refused = client.patch(path, headers=owner, json={"source_key": "taken"})
    assert refused.status_code == 409, refused.text
    assert client.get(path, headers=owner).json()["source_key"] == "free"


def test_a_source_with_intakes_cannot_be_deleted(client, owner):
    src = source_id(client, owner)
    create_intake(client, owner, src)
    refused = client.delete(f"{SOURCES}/{src}", headers=owner)
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == {"error": "has_dependents"}


def test_an_intake_with_events_cannot_be_deleted(client, owner):
    target = intake_id(client, owner)
    create_event(client, owner, target)
    assert client.delete(f"{INTAKES}/{target}", headers=owner).status_code == 409


def test_an_import_keeps_the_old_source_id(client, owner):
    imported = create_source(client, owner, legacy_id=3, source_key="legacy-diary")
    assert imported.status_code == 201, imported.text
    assert imported.json()["id"] == 3
    by_legacy = client.get(f"{SOURCES}/legacy/3", headers=owner)
    assert by_legacy.status_code == 200, by_legacy.text
    assert by_legacy.json()["source_key"] == "legacy-diary"
    # The imported id is what intakes point at.
    assert create_intake(client, owner, 3).status_code == 201


def test_a_repeated_import_conflicts_instead_of_duplicating(client, owner):
    src = source_id(client, owner)
    assert create_intake(client, owner, src, legacy_id=11).status_code == 201
    assert create_intake(client, owner, src, legacy_id=11).status_code == 409
