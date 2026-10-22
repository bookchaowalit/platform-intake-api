"""Listing, grouping and the lifecycle of sources, intakes and their event trail."""

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


def ids(response):
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["items"]]


def test_sources_filter_by_kind_status_domain_and_dataset(client, owner):
    api = create_source(client, owner, source_kind="api", status="active").json()
    create_source(client, owner, source_kind="email", domain="mail", dataset="inbox")
    assert ids(client.get(SOURCES, headers=owner, params={"source_kind": "api"})) == [
        api["id"]
    ]
    assert ids(client.get(SOURCES, headers=owner, params={"status": "active"})) == [
        api["id"]
    ]
    by_domain = client.get(SOURCES, headers=owner, params={"domain": "mail"})
    assert [s["dataset"] for s in by_domain.json()["items"]] == ["inbox"]
    by_key = client.get(
        SOURCES, headers=owner, params={"source_key": api["source_key"]}
    )
    assert ids(by_key) == [api["id"]]


def test_intakes_filter_by_source_status_and_lease_owner(client, owner):
    src = source_id(client, owner)
    other = source_id(client, owner)
    queued = create_intake(client, owner, src).json()
    claimed = create_intake(
        client, owner, src, status="processing", lease_owner="worker-1"
    ).json()
    elsewhere = create_intake(client, owner, other).json()
    assert ids(client.get(INTAKES, headers=owner, params={"source_id": src})) == [
        queued["id"],
        claimed["id"],
    ]
    assert ids(client.get(INTAKES, headers=owner, params={"status": "queued"})) == [
        queued["id"],
        elsewhere["id"],
    ]
    assert ids(
        client.get(INTAKES, headers=owner, params={"lease_owner": "worker-1"})
    ) == [claimed["id"]]


def test_an_intake_is_found_by_its_key(client, owner):
    intake = create_intake(
        client, owner, source_id(client, owner), intake_key="find-me"
    ).json()
    found = client.get(INTAKES, headers=owner, params={"intake_key": "find-me"})
    assert ids(found) == [intake["id"]]


def test_unclaimed_intakes_are_listed_with_null(client, owner):
    src = source_id(client, owner)
    free = create_intake(client, owner, src).json()
    create_intake(client, owner, src, lease_owner="worker-2")
    assert ids(client.get(INTAKES, headers=owner, params={"null": "lease_owner"})) == [
        free["id"]
    ]


def test_the_event_trail_lists_one_intakes_events_in_order(client, owner):
    target = intake_id(client, owner)
    noise = intake_id(client, owner)
    queued = create_event(
        client, owner, target, event_type="queued", to_status="queued"
    )
    claimed = create_event(client, owner, target, from_status="queued")
    create_event(client, owner, noise)
    trail = client.get(EVENTS, headers=owner, params={"intake_id": target})
    assert ids(trail) == [queued.json()["id"], claimed.json()["id"]]
    claims = client.get(EVENTS, headers=owner, params={"event_type": "claimed"})
    assert len(ids(claims)) == 2


def test_stats_count_intakes_per_status(client, owner):
    src = source_id(client, owner)
    create_intake(client, owner, src)
    create_intake(client, owner, src)
    create_intake(client, owner, src, status="failed", error_code="parse")
    stats = client.get(f"{INTAKES}/stats", headers=owner, params={"group_by": "status"})
    assert stats.status_code == 200, stats.text
    assert stats.json()["groups"] == {"queued": 2, "failed": 1}


def test_stats_count_sources_per_kind_and_events_per_type(client, owner):
    create_source(client, owner, source_kind="api")
    create_source(client, owner, source_kind="api")
    create_source(client, owner, source_kind="calendar")
    kinds = client.get(
        f"{SOURCES}/stats", headers=owner, params={"group_by": "source_kind"}
    )
    assert kinds.json()["groups"] == {"api": 2, "calendar": 1}
    target = intake_id(client, owner)
    create_event(client, owner, target, event_type="queued", to_status="queued")
    create_event(client, owner, target)
    events = client.get(
        f"{EVENTS}/stats", headers=owner, params={"group_by": "event_type"}
    )
    assert events.json()["groups"] == {"queued": 1, "claimed": 1}


def test_stats_refuse_a_field_that_is_not_a_filter(client, owner):
    for path, field in (
        (SOURCES, "privacy_class"),
        (INTAKES, "payload_kind"),
        (EVENTS, "to_status"),
    ):
        stats = client.get(f"{path}/stats", headers=owner, params={"group_by": field})
        assert stats.status_code == 422, path


def test_claiming_an_intake_bumps_the_version(client, owner):
    target = intake_id(client, owner)
    path = f"{INTAKES}/{target}"
    claimed = client.patch(
        path,
        headers=owner,
        json={
            "status": "processing",
            "claimed_at": "2026-10-22T08:00:00+00:00",
            "lease_owner": "worker-1",
            "lease_expires_at": "2026-10-22T08:10:00+00:00",
            "attempt_count": 1,
            "expected_version": 1,
        },
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["version"] == 2
    assert claimed.json()["lease_owner"] == "worker-1"
    # A second worker holding the old version loses the race.
    late = client.patch(
        path, headers=owner, json={"lease_owner": "worker-2", "expected_version": 1}
    )
    assert late.status_code == 409, late.text
    assert client.get(path, headers=owner).json()["lease_owner"] == "worker-1"


def test_releasing_a_lease_clears_it(client, owner):
    target = intake_id(client, owner, lease_owner="worker-1", status="processing")
    released = client.patch(
        f"{INTAKES}/{target}",
        headers=owner,
        json={"status": "queued", "lease_owner": None, "lease_expires_at": None},
    )
    assert released.status_code == 200, released.text
    assert released.json()["lease_owner"] is None


def test_a_patch_that_changes_nothing_keeps_the_version(client, owner):
    source = create_source(client, owner, display_name="Same").json()
    same = client.patch(
        f"{SOURCES}/{source['id']}", headers=owner, json={"display_name": "Same"}
    )
    assert same.status_code == 200, same.text
    assert same.json()["version"] == 1


def test_an_unused_source_can_be_deleted(client, owner):
    src = source_id(client, owner)
    assert client.delete(f"{SOURCES}/{src}", headers=owner).status_code == 204
    assert client.get(f"{SOURCES}/{src}", headers=owner).status_code == 404


def test_an_intake_can_be_deleted_after_its_events(client, owner):
    target = intake_id(client, owner)
    event = create_event(client, owner, target).json()
    assert client.delete(f"{EVENTS}/{event['id']}", headers=owner).status_code == 204
    assert client.delete(f"{INTAKES}/{target}", headers=owner).status_code == 204
