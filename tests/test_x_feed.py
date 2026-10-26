"""The X feed source (SPEC-002): batch ingest, idempotency, validation, token scope, state upserts,
search, lake export and retention. Rows come from tests/x_feed_helpers.py and are fake test data."""

import uuid
from datetime import datetime
from typing import Any

import pytest
from x_feed_helpers import (
    COLLECTED,
    COLLECTOR_SCOPES,
    PULLS,
    post_id,
    pull_id,
    row,
    rows,
    send,
)


@pytest.fixture
def workspace() -> uuid.UUID:
    return uuid.uuid4()


def mint(
    harness: Any, platform: Any, ws: uuid.UUID, scopes: set[str]
) -> dict[str, str]:
    actor = uuid.uuid4()
    platform.grants[actor] = set(scopes)
    return harness.token(actor, ws)


@pytest.fixture
def collector(harness, platform, workspace) -> dict[str, str]:
    """The Grok Bot Chief Data token: x-feed scopes only."""
    return mint(harness, platform, workspace, COLLECTOR_SCOPES)


@pytest.fixture
def boss(harness, platform, workspace) -> dict[str, str]:
    """The workspace owner (every intake permission), same workspace as the collector."""
    return mint(harness, platform, workspace, set(harness.cell.permissions()))


def at(value: str) -> datetime:
    return datetime.fromisoformat(value)


def ingest(
    client: Any, headers: dict[str, str], posts: list[dict[str, Any]], pid: str
) -> Any:
    response = client.post(
        PULLS,
        headers=headers,
        json={"pull_id": pid, "collected_at": COLLECTED, "posts": posts},
    )
    assert response.status_code == 200, response.text
    return response.json()


# --- AC-01..03: ingest and idempotency --------------------------------------------------------


def test_a_pull_lands_posts_sightings_and_an_intake_row(client, collector, boss):
    pid = pull_id()
    result = ingest(client, collector, rows(20), pid)
    assert result["accepted"] == 20
    assert result["rejected"] == []
    assert result["posts_new"] == 20
    assert result["sightings_new"] == 20

    posts = client.get("/v1/x-posts", headers=boss, params={"limit": 100}).json()
    assert len(posts["items"]) == 20
    intake = client.get(
        "/v1/intakes", headers=boss, params={"intake_key": f"x-feed:{pid}"}
    ).json()["items"]
    assert len(intake) == 1
    assert intake[0]["status"] == "landed"
    assert intake[0]["record_count"] == 20
    assert intake[0]["dataset"] == "x_feed"
    events = client.get(
        "/v1/intake-events", headers=boss, params={"intake_id": intake[0]["id"]}
    ).json()["items"]
    assert [e["event_type"] for e in events] == ["landed"]


def test_the_source_is_registered_and_its_last_ingest_is_stamped(
    client, collector, boss
):
    ingest(client, collector, rows(2), pull_id())
    sources = client.get(
        "/v1/sources", headers=boss, params={"source_key": "x-feed"}
    ).json()["items"]
    assert len(sources) == 1
    assert sources[0]["source_kind"] == "api"
    assert sources[0]["status"] == "active"
    assert sources[0]["last_ingested_at"] is not None


def test_resending_the_same_pull_duplicates_nothing(client, collector, boss):
    pid = pull_id()
    ingest(client, collector, rows(20), pid)
    again = ingest(client, collector, rows(20), pid)
    assert again["posts_new"] == 0
    assert again["sightings_new"] == 0
    assert again["sightings_duplicate"] == 20
    sightings = client.get(
        "/v1/x-sightings", headers=boss, params={"pull_id": pid, "limit": 100}
    ).json()["items"]
    assert len(sightings) == 20
    intake = client.get(
        "/v1/intakes", headers=boss, params={"intake_key": f"x-feed:{pid}"}
    ).json()["items"]
    assert len(intake) == 1


def test_the_same_post_from_two_queries_is_one_post_and_two_sightings(
    client, collector, boss
):
    pid = pull_id()
    result = ingest(
        client,
        collector,
        [row(1, query_id="q-ai"), row(1, query_id="q-agents", score=0.99)],
        pid,
    )
    assert result["posts_new"] == 1
    assert result["sightings_new"] == 2
    posts = client.get(
        "/v1/x-posts", headers=boss, params={"post_id": post_id(1)}
    ).json()["items"]
    assert len(posts) == 1


def test_a_later_pull_refreshes_metrics_and_keeps_first_collected(
    client, collector, boss
):
    ingest(client, collector, [row(3, likes=5)], pull_id())
    later = client.post(
        PULLS,
        headers=collector,
        json={
            "pull_id": pull_id(),
            "collected_at": "2026-10-26T17:30:00+07:00",
            "posts": [row(3, likes=50, collected_at=None)],
        },
    )
    assert later.status_code == 200, later.text
    assert later.json()["posts_updated"] == 1
    post = client.get(
        "/v1/x-posts", headers=boss, params={"post_id": post_id(3)}
    ).json()["items"][0]
    assert post["likes"] == 50
    assert at(post["first_collected_at"]) == at("2026-10-25T23:30:00Z")
    assert at(post["last_collected_at"]) == at("2026-10-26T10:30:00Z")


def test_an_older_resend_does_not_roll_metrics_back(client, collector, boss):
    ingest(
        client,
        collector,
        [row(4, likes=99, collected_at="2026-10-26T17:30:00+07:00")],
        pull_id(),
    )
    ingest(client, collector, [row(4, likes=1)], pull_id())
    post = client.get(
        "/v1/x-posts", headers=boss, params={"post_id": post_id(4)}
    ).json()["items"][0]
    assert post["likes"] == 99


# --- AC-04..06: validation --------------------------------------------------------------------


def test_bad_rows_are_reported_and_good_rows_still_land(client, collector):
    posts = [
        row(1),
        row(2, surprise="field"),
        row(3, likes=-1),
        row(4, post_id="not-a-number"),
        {k: v for k, v in row(5).items() if k != "requesting_chief"},
    ]
    result = ingest(client, collector, posts, pull_id())
    assert result["accepted"] == 1
    rejected = {r["index"]: r for r in result["rejected"]}
    assert sorted(rejected) == [1, 2, 3, 4]
    assert rejected[1]["fields"] == ["surprise"]
    assert rejected[1]["reason"] == "unknown_field"
    assert rejected[2]["fields"] == ["likes"]
    assert rejected[3]["fields"] == ["post_id"]
    assert rejected[4]["fields"] == ["requesting_chief"]


def test_a_pull_with_no_valid_row_is_refused(client, collector):
    response = send(client, collector, [row(1, likes="lots")])
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "no_valid_rows"


def test_more_than_2000_posts_is_refused(client, collector):
    response = send(client, collector, [row(n) for n in range(2001)])
    assert response.status_code == 413
    assert response.json()["detail"]["error"] == "batch_too_large"


def test_unknown_top_level_fields_and_bad_pull_ids_are_refused(client, collector):
    assert send(client, collector, rows(1), extra=1).status_code == 422
    bad = client.post(
        PULLS,
        headers=collector,
        json={
            "pull_id": "has spaces/and slashes",
            "collected_at": COLLECTED,
            "posts": rows(1),
        },
    )
    assert bad.status_code == 422


def test_sheet_style_values_are_normalised(client, collector, boss):
    pid = pull_id()
    result = ingest(
        client,
        collector,
        [
            row(
                7,
                post_id=int(post_id(7)),
                author_handle="@test_user_7",
                likes="1,234",
                top="TRUE",
                tag=["ai", "agents"],
                query_id="",
                posted_at="Sun Oct 25 23:00:00 +0000 2026",
                text="TEST DATA nul\x00byte",
            )
        ],
        pid,
    )
    assert result["accepted"] == 1, result
    post = client.get(
        "/v1/x-posts", headers=boss, params={"post_id": post_id(7)}
    ).json()["items"][0]
    assert post["author_handle"] == "test_user_7"
    assert post["likes"] == 1234
    assert at(post["posted_at"]) == at("2026-10-25T23:00:00Z")
    assert "\x00" not in post["text"]
    sighting = client.get(
        "/v1/x-sightings", headers=boss, params={"pull_id": pid}
    ).json()["items"][0]
    assert sighting["top"] is True
    assert sighting["tag"] == "ai,agents"
    assert sighting["query_id"] == "-"


def test_post_text_is_stored_as_given_not_rendered(client, collector, boss):
    ingest(client, collector, [row(8)], pull_id())
    post = client.get(
        "/v1/x-posts", headers=boss, params={"post_id": post_id(8)}
    ).json()["items"][0]
    assert post["text"].endswith("<script>alert(1)</script>")


# --- AC-07..08: token scope -------------------------------------------------------------------


def test_the_collector_token_cannot_touch_the_rest_of_intake(client, collector):
    assert client.get("/v1/sources", headers=collector).status_code == 403
    assert client.get("/v1/intakes", headers=collector).status_code == 403
    created = client.post(
        "/v1/sources",
        headers={**collector, "Idempotency-Key": "test-key-0001"},
        json={
            "source_key": "evil",
            "display_name": "x",
            "source_kind": "api",
            "domain": "d",
            "dataset": "d",
        },
    )
    assert created.status_code == 403


def test_ingest_needs_the_x_post_write_permission(client, harness, platform, workspace):
    reader = mint(
        harness, platform, workspace, {"intake.x-post:read", "intake.x-sighting:read"}
    )
    assert send(client, reader, rows(1)).status_code == 403
    assert client.post(PULLS, json={"pull_id": "p", "posts": []}).status_code == 401


def test_pulls_stay_inside_their_workspace(client, harness, platform, collector):
    ingest(client, collector, rows(3), pull_id())
    other = mint(harness, platform, uuid.uuid4(), set(harness.cell.permissions()))
    assert client.get("/v1/x-posts", headers=other).json()["items"] == []
    assert client.get("/v1/x-feed/search", headers=other).json()["items"] == []


# --- AC-09: collector state -------------------------------------------------------------------


def test_watchlist_upsert_is_idempotent_on_chief_type_value(client, collector):
    body = {
        "rows": [
            {
                "requesting_chief": "chief-data",
                "type": "account",
                "value": "test_account",
                "purpose": "TEST DATA",
                "added_date": "2026-10-20",
                "last_used": "2026-10-26",
                "tag": "ai",
            }
        ]
    }
    first = client.put("/v1/x-feed/watchlist", headers=collector, json=body)
    assert first.status_code == 200, first.text
    assert first.json() == {"received": 1, "inserted": 1, "updated": 0}
    body["rows"][0]["purpose"] = "TEST DATA changed"
    second = client.put("/v1/x-feed/watchlist", headers=collector, json=body).json()
    assert second == {"received": 1, "inserted": 0, "updated": 1}
    items = client.get("/v1/x-watchlist", headers=collector).json()["items"]
    assert len(items) == 1
    assert items[0]["purpose"] == "TEST DATA changed"


def test_query_plan_upsert_keeps_one_row_per_query(client, collector):
    plan = {
        "query_id": "q1",
        "query": '(agents OR "ai agent") lang:en -is:retweet',
        "requesting_chiefs": "chief-data,chief-of-staff",
        "tags": "ai,agents",
        "watchlist_rows": "2,3",
        "priority": 1,
        "last_since_id": post_id(0),
        "last_run_at": COLLECTED,
        "runs": 3,
        "calls_total": 12,
        "posts_total": 80,
        "new_posts_last": 9,
        "avg_yield": 6.6,
        "status": "active",
        "calls_last_run": 4,
        "yield_last6": "5,7,9,6,8,9",
        "query_type": "keyword",
        "lang_filter": "en",
    }
    assert (
        client.put(
            "/v1/x-feed/query-plan", headers=collector, json={"rows": [plan]}
        ).status_code
        == 200
    )
    plan["runs"] = 4
    again = client.put(
        "/v1/x-feed/query-plan", headers=collector, json={"rows": [plan]}
    ).json()
    assert again["updated"] == 1
    items = client.get("/v1/x-query-plan", headers=collector).json()["items"]
    assert [i["runs"] for i in items] == [4]


# --- AC-10: search and top --------------------------------------------------------------------


def test_search_by_text_tag_and_chief(client, collector, boss):
    ingest(client, collector, rows(20), pull_id())
    found = client.get(
        "/v1/x-feed/search", headers=boss, params={"q": "TEST DATA 13:"}
    ).json()
    assert [p["post_id"] for p in found["items"]] == [post_id(13)]
    by_tag = client.get(
        "/v1/x-feed/search", headers=boss, params={"tag": "agents"}
    ).json()["items"]
    assert by_tag
    assert all("agents" in p["tags"] for p in by_tag)
    by_chief = client.get(
        "/v1/x-feed/search",
        headers=boss,
        params={"chief": "chief-health", "limit": 100},
    ).json()["items"]
    assert len(by_chief) == 5
    assert all(p["chiefs"] == ["chief-health"] for p in by_chief)


def test_search_treats_like_wildcards_as_text(client, collector, boss):
    ingest(client, collector, rows(3), pull_id())
    assert (
        client.get("/v1/x-feed/search", headers=boss, params={"q": "%"}).json()["items"]
        == []
    )


def test_top_orders_by_score(client, collector, boss):
    ingest(client, collector, rows(20), pull_id())
    top = client.get(
        "/v1/x-feed/top",
        headers=boss,
        params={"since": "2026-10-01T00:00:00Z", "limit": 3},
    ).json()["items"]
    assert [p["post_id"] for p in top] == [post_id(19), post_id(18), post_id(17)]


def test_search_needs_read_permission(client, harness, platform, workspace):
    nobody = mint(harness, platform, workspace, set())
    assert client.get("/v1/x-feed/search", headers=nobody).status_code == 403


# --- AC-11: lake export -----------------------------------------------------------------------


def test_export_rows_then_mark_the_pull_verified(client, collector, boss):
    pid = pull_id()
    ingest(client, collector, rows(5), pid)
    export = client.get(f"/v1/x-feed/pulls/{pid}/rows", headers=boss).json()
    assert export["record_count"] == 5
    first = export["items"][0]
    assert set(first) >= {
        "sighting_key",
        "pull_id",
        "collected_at",
        "requesting_chief",
        "watch_type",
        "watch_value",
        "post_id",
        "post_url",
        "author_handle",
        "posted_at",
        "text",
        "likes",
        "reposts",
        "replies",
        "views",
        "tag",
        "query_id",
        "score",
        "top",
    }
    marked = client.post(
        f"/v1/x-feed/pulls/{pid}/exported",
        headers=boss,
        json={
            "record_count": 5,
            "lake_run_id": "2026-10-26-test",
            "lake_bronze_object_key": "bronze/domain=social/dataset=x_feed/test.parquet",
            "lake_manifest_key": "control/manifests/test.json",
        },
    )
    assert marked.status_code == 200, marked.text
    intake = client.get(
        "/v1/intakes", headers=boss, params={"intake_key": f"x-feed:{pid}"}
    ).json()["items"][0]
    assert intake["status"] == "verified"
    assert intake["lake_bronze_object_key"].endswith("test.parquet")
    posts = client.get("/v1/x-posts", headers=boss, params={"limit": 100}).json()[
        "items"
    ]
    assert all(p["exported_at"] for p in posts)


def test_marking_a_pull_that_changed_since_the_read_is_refused(client, collector, boss):
    pid = pull_id()
    ingest(client, collector, rows(5), pid)
    ingest(client, collector, rows(2, start=10), pid)
    marked = client.post(
        f"/v1/x-feed/pulls/{pid}/exported",
        headers=boss,
        json={"record_count": 5, "lake_run_id": "r", "lake_bronze_object_key": "k"},
    )
    assert marked.status_code == 409
    assert marked.json()["detail"]["error"] == "pull_changed"


def test_new_rows_after_export_put_the_pull_back_to_landed(client, collector, boss):
    pid = pull_id()
    ingest(client, collector, rows(2), pid)
    client.post(
        f"/v1/x-feed/pulls/{pid}/exported",
        headers=boss,
        json={"record_count": 2, "lake_run_id": "r", "lake_bronze_object_key": "k"},
    )
    ingest(client, collector, rows(1, start=30), pid)
    intake = client.get(
        "/v1/intakes", headers=boss, params={"intake_key": f"x-feed:{pid}"}
    ).json()["items"][0]
    assert intake["status"] == "landed"
    assert intake["record_count"] == 3


def test_the_collector_cannot_mark_exports(client, collector):
    pid = pull_id()
    ingest(client, collector, rows(1), pid)
    response = client.post(
        f"/v1/x-feed/pulls/{pid}/exported",
        headers=collector,
        json={"record_count": 1, "lake_run_id": "r", "lake_bronze_object_key": "k"},
    )
    assert response.status_code == 403


def test_an_unknown_pull_is_not_found(client, boss):
    assert (
        client.get("/v1/x-feed/pulls/test-pull-missing/rows", headers=boss).status_code
        == 404
    )


# --- AC-12: retention -------------------------------------------------------------------------


def test_exported_text_older_than_the_retention_window_is_purged(
    client, collector, boss
):
    old = pull_id()
    ingest(client, collector, [row(1, collected_at="2026-01-01T00:00:00Z")], old)
    client.post(
        f"/v1/x-feed/pulls/{old}/exported",
        headers=boss,
        json={"record_count": 1, "lake_run_id": "r", "lake_bronze_object_key": "k"},
    )
    # The next ingest sweeps: the old exported post loses its text, its sighting goes (the lake has both).
    result = ingest(
        client, collector, [row(2, collected_at="2026-01-01T00:00:00Z")], pull_id()
    )
    assert result["purged_text"] == 1
    assert result["purged_sightings"] == 1
    again = ingest(client, collector, [row(3)], pull_id())
    assert again["purged_text"] == 0
    assert again["purged_sightings"] == 0
    posts = {
        p["post_id"]: p
        for p in client.get("/v1/x-posts", headers=boss, params={"limit": 100}).json()[
            "items"
        ]
    }
    assert posts[post_id(1)]["text"] is None
    assert posts[post_id(1)]["text_purged_at"]
    assert (
        posts[post_id(2)]["text"] is not None
    )  # never exported: kept until the lake has it
