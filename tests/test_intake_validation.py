"""What the intake cell refuses: unknown kinds and statuses, oversize keys, bad references."""

import uuid

import pytest
from intake_helpers import (
    EVENTS,
    INTAKES,
    SOURCES,
    create_event,
    create_intake,
    create_source,
    intake_id,
    source_id,
)


@pytest.mark.parametrize(
    "missing", ["source_key", "display_name", "source_kind", "domain", "dataset"]
)
def test_a_source_needs_its_key_name_kind_domain_and_dataset(client, owner, missing):
    body = {
        "source_key": f"src-{missing}",
        "display_name": "Diary",
        "source_kind": "manual",
        "domain": "life",
        "dataset": "diary",
    }
    del body[missing]
    assert client.post(SOURCES, headers=owner, json=body).status_code == 422


def test_source_kind_must_be_a_known_kind(client, owner):
    assert create_source(client, owner, source_kind="ftp").status_code == 422
    assert create_source(client, owner, source_kind="webhook").status_code == 201


def test_source_enums_refuse_unknown_values(client, owner):
    assert create_source(client, owner, owner_scope="family").status_code == 422
    assert create_source(client, owner, privacy_class="secret").status_code == 422
    assert create_source(client, owner, ingest_mode="realtime").status_code == 422
    assert create_source(client, owner, status="deleted").status_code == 422


def test_source_key_is_limited_to_64_characters(client, owner):
    assert create_source(client, owner, source_key="k" * 65).status_code == 422
    assert create_source(client, owner, source_key="k" * 64).status_code == 201


def test_source_name_domain_and_dataset_have_length_limits(client, owner):
    assert create_source(client, owner, display_name="n" * 161).status_code == 422
    assert create_source(client, owner, domain="d" * 81).status_code == 422
    assert create_source(client, owner, dataset="s" * 121).status_code == 422
    fits = create_source(
        client, owner, display_name="n" * 160, domain="d" * 80, dataset="s" * 120
    )
    assert fits.status_code == 201, fits.text


@pytest.mark.parametrize(
    "missing",
    [
        "intake_key",
        "source_id",
        "domain",
        "dataset",
        "payload_kind",
        "input_ref",
        "idempotency_key",
    ],
)
def test_an_intake_needs_every_required_field(client, owner, missing):
    body = {
        "intake_key": f"in-{missing}",
        "source_id": source_id(client, owner),
        "domain": "finance",
        "dataset": "statements",
        "payload_kind": "json",
        "input_ref": "inbox/a.json",
        "idempotency_key": f"idem-{missing}",
    }
    del body[missing]
    assert client.post(INTAKES, headers=owner, json=body).status_code == 422


def test_payload_kind_status_and_requester_must_be_known(client, owner):
    src = source_id(client, owner)
    assert create_intake(client, owner, src, payload_kind="xml").status_code == 422
    assert create_intake(client, owner, src, status="done").status_code == 422
    assert create_intake(client, owner, src, requested_by="robot").status_code == 422
    assert create_intake(client, owner, src, payload_kind="parquet").status_code == 201


def test_intake_keys_and_refs_have_length_limits(client, owner):
    src = source_id(client, owner)
    for field, limit in (
        ("intake_key", 96),
        ("idempotency_key", 160),
        ("input_ref", 240),
        ("source_batch_ref", 160),
        ("raw_sha256", 64),
        ("lake_manifest_key", 512),
        ("error_code", 80),
        ("error_message", 500),
    ):
        too_long = create_intake(client, owner, src, **{field: "x" * (limit + 1)})
        assert too_long.status_code == 422, field
        fits = create_intake(client, owner, src, **{field: "y" * limit})
        assert fits.status_code == 201, (field, fits.text)


def test_attempt_and_record_counts_cannot_be_negative(client, owner):
    src = source_id(client, owner)
    assert create_intake(client, owner, src, attempt_count=-1).status_code == 422
    assert create_intake(client, owner, src, record_count=-1).status_code == 422
    assert create_intake(client, owner, src, record_count=0).status_code == 201


def test_lease_expiry_must_be_a_timestamp(client, owner):
    src = source_id(client, owner)
    refused = create_intake(client, owner, src, lease_expires_at="in ten minutes")
    assert refused.status_code == 422


def test_an_intake_cannot_point_at_a_missing_source(client, owner):
    response = create_intake(client, owner, 999_999_999)
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == {"error": "reference_not_found"}


def test_an_intake_cannot_point_at_another_workspaces_source(
    client, owner, harness, platform
):
    stranger_actor = uuid.uuid4()
    platform.grants[stranger_actor] = set(harness.cell.permissions())
    stranger = harness.token(stranger_actor, uuid.uuid4())
    theirs = source_id(client, stranger)
    assert create_intake(client, owner, theirs).status_code == 422


def test_an_event_needs_an_intake_a_type_and_a_target_status(client, owner):
    target = intake_id(client, owner)
    for missing in ("intake_id", "event_type", "to_status"):
        body = {"intake_id": target, "event_type": "queued", "to_status": "queued"}
        del body[missing]
        assert client.post(EVENTS, headers=owner, json=body).status_code == 422, missing


def test_event_type_must_be_a_known_transition(client, owner):
    target = intake_id(client, owner)
    assert create_event(client, owner, target, event_type="paused").status_code == 422
    assert (
        create_event(client, owner, target, event_type="lease_renewed").status_code
        == 201
    )


def test_event_status_names_and_reason_have_length_limits(client, owner):
    target = intake_id(client, owner)
    assert create_event(client, owner, target, to_status="s" * 33).status_code == 422
    assert create_event(client, owner, target, from_status="s" * 33).status_code == 422
    assert create_event(client, owner, target, actor="a" * 81).status_code == 422
    assert create_event(client, owner, target, reason="r" * 501).status_code == 422
    assert create_event(client, owner, target, reason="r" * 500).status_code == 201


def test_an_event_cannot_point_at_a_missing_intake(client, owner):
    assert create_event(client, owner, 999_999_999).status_code == 422


def test_a_required_reference_cannot_be_cleared_by_a_patch(client, owner):
    target = intake_id(client, owner)
    cleared = client.patch(
        f"{INTAKES}/{target}", headers=owner, json={"source_id": None}
    )
    assert cleared.status_code == 422, cleared.text
    assert cleared.json()["detail"] == {
        "error": "invalid_value",
        "fields": ["source_id"],
    }
