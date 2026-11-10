"""The X intel read API (SPEC-003) against the throwaway cluster: a fake ``x_intel`` schema with the six relations
the API reads, a read-only ``x_intel_reader`` role granted exactly as in production, and the fake platform.
Every row is clearly fake test data."""

import uuid
from typing import Any

import pytest

from cellkit.db import PORT
from solo_intake import x_intel

READER = "x_intel_reader"
OWNER_WS = uuid.UUID("00000000-0000-4000-8000-00000000000a")
DENY = "Acme Corp\n# comment\nGlobex"

SCHEMA = f"""
DROP SCHEMA IF EXISTS x_intel CASCADE;
CREATE SCHEMA x_intel;
CREATE TABLE x_intel.mart_x_signal_priority (
  post_id text, collected_at timestamptz, collected_ict timestamp, domain text, topic text, category text,
  signal_type text, alert_tier text, route text, cred_tier text, content_label text, opportunity_score bigint,
  verification_status text, suggested_action text, author_handle text, post_url text, post_text text,
  likes bigint, reposts bigint, views bigint, priority numeric);
CREATE TABLE x_intel.mart_x_domain_hourly (hour_ict timestamp, domain text, signals bigint, alerts bigint,
  urgent bigint, opportunities bigint, strong_sources bigint, avg_score numeric);
CREATE TABLE x_intel.claims (claim_id text, claim text, verification_status text, queue_state text,
  priority double precision, next_check timestamptz, last_checked timestamptz, first_seen_link text, checked_by text);
CREATE VIEW x_intel.mart_claims_queue AS SELECT * FROM x_intel.claims WHERE queue_state = 'open';
CREATE TABLE x_intel.x_analyses (report_week text, analysis text, rank bigint, item text, post_id text, link text,
  topic text, book_domain text, geo text, value text, value_kind text, source_tier text, metric text, note text);
CREATE TABLE x_intel.digest_log (digest_id text, kind text, window_start timestamptz, window_end timestamptz,
  status text, signals int, sent_messages int, cost_usd numeric, error text, updated_at timestamptz,
  tokens_in int, tokens_out int);
CREATE TABLE x_intel.secret_stuff (x text);
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{READER}') THEN
  CREATE ROLE {READER} LOGIN; END IF; END $$;
GRANT USAGE ON SCHEMA x_intel TO {READER};
GRANT SELECT ON x_intel.mart_x_signal_priority, x_intel.mart_x_domain_hourly, x_intel.mart_claims_queue,
  x_intel.claims, x_intel.x_analyses, x_intel.digest_log TO {READER};
"""


def sig(pid: str, hours_ago: float, **kw: Any) -> dict[str, Any]:
    row = {
        "post_id": pid,
        "domain": "D2 Economy & Money",
        "alert_tier": "none",
        "signal_type": "News",
        "opportunity_score": 1,
        "post_text": f"TEST DATA {pid}",
        "post_url": f"https://x.com/test/status/{pid}",
        "author_handle": "test_user",
        "priority": 10,
        "hours_ago": hours_ago,
    }
    row.update(kw)
    return row


SIGNALS = [
    sig("1", 1, alert_tier="urgent_candidate", priority=2050, domain="D5 Technology"),
    sig("2", 2, alert_tier="digest", priority=1080, opportunity_score=4),
    sig("3", 3, post_text="TEST DATA deal with ACME corp", priority=3000),
    sig("4", 30, priority=5000),  # older than the default 24 h
    sig("5", 0.5, post_text="TEST DATA " + "x" * 1500, priority=5),
    sig("6", 4, post_text="TEST DATA 100%_literal", priority=6),
]


@pytest.fixture
def lake(harness):
    with harness.cluster.connect("postgres", autocommit=True) as conn:
        conn.execute(SCHEMA)
        for s in SIGNALS:
            conn.execute(
                "INSERT INTO x_intel.mart_x_signal_priority (post_id, collected_at, domain, alert_tier, signal_type,"
                " opportunity_score, post_text, post_url, author_handle, priority) VALUES"
                " (%s, now() - make_interval(secs => %s), %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    s["post_id"],
                    s["hours_ago"] * 3600,
                    s["domain"],
                    s["alert_tier"],
                    s["signal_type"],
                    s["opportunity_score"],
                    s["post_text"],
                    s["post_url"],
                    s["author_handle"],
                    s["priority"],
                ),
            )
        conn.execute(
            "INSERT INTO x_intel.mart_x_domain_hourly VALUES"
            " ((now() AT TIME ZONE 'Asia/Bangkok') - interval '1 hour', 'D2 Economy & Money', 5, 2, 0, 1, 1, 1),"
            " ((now() AT TIME ZONE 'Asia/Bangkok') - interval '2 hour', 'D2 Economy & Money', 3, 0, 0, 0, 0, 1),"
            " ((now() AT TIME ZONE 'Asia/Bangkok') - interval '3 hour', 'Globex watch', 2, 0, 0, 0, 0, 1),"
            " ((now() AT TIME ZONE 'Asia/Bangkok') - interval '20 day', 'D1 World & Politics', 9, 0, 0, 0, 0, 1)"
        )
        conn.execute(
            "INSERT INTO x_intel.claims VALUES ('c1', 'TEST rates fall', 'unverified', 'open', 1, now(), null,"
            " 'https://example.com/c1', null), ('c2', 'TEST Globex merger', null, 'open', 2, null, null, null, null),"
            " ('c3', 'TEST old claim', 'true', 'closed', 3, null, now(), null, 'chief-data')"
        )
        conn.execute(
            "INSERT INTO x_intel.x_analyses (report_week, analysis, rank, item) VALUES"
            " ('2026-W44', 'top_topics', 1, 'old'), ('2026-W45', 'top_topics', 1, 'TEST ai agents'),"
            " ('2026-W45', 'top_topics', 2, 'TEST acme corp deal')"
        )
        conn.execute(
            "INSERT INTO x_intel.digest_log (digest_id, kind, window_end, status, signals, cost_usd, updated_at)"
            " VALUES ('midday:2026-11-10', 'midday', now(), 'sent', 189, 0.0012, now()),"
            " ('morning:2026-11-10', 'morning', now() - interval '8 hour', 'sent', 522, 0.0011, now())"
        )
    return f"host={harness.cluster.socket_dir} port={PORT} user={READER} dbname={harness.cluster.names.database}"


@pytest.fixture
def env(monkeypatch, lake):
    monkeypatch.setenv(x_intel.DB_ENV, lake)
    monkeypatch.setenv(x_intel.WORKSPACE_ENV, str(OWNER_WS))
    monkeypatch.setenv(x_intel.DENYLIST_ENV, DENY)


def mint(
    harness: Any, platform: Any, ws: uuid.UUID, scopes: set[str]
) -> dict[str, str]:
    actor = uuid.uuid4()
    platform.grants[actor] = set(scopes)
    return harness.token(actor, ws)


@pytest.fixture
def owner_x(harness, platform):
    return mint(harness, platform, OWNER_WS, {"intake.x-post:read"})


@pytest.fixture
def api(env, harness, platform):
    return harness.client(platform)


def get(api, headers, path, **params):
    return api.get(f"/v1/x-intel/{path}", headers=headers, params=params)


# X1 ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "missing", [x_intel.DB_ENV, x_intel.WORKSPACE_ENV, x_intel.DENYLIST_ENV]
)
def test_x1_missing_configuration_fails_closed(
    monkeypatch, env, harness, platform, owner_x, missing
):
    monkeypatch.setenv(missing, "")
    r = get(harness.client(platform), owner_x, "signals")
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "x_intel_not_configured"


def test_x1_database_down_is_503(monkeypatch, env, harness, platform, owner_x):
    monkeypatch.setenv(
        x_intel.DB_ENV,
        "host=/nonexistent port=1 user=nobody dbname=none connect_timeout=1",
    )
    r = get(harness.client(platform), owner_x, "status")
    assert (r.status_code, r.json()["detail"]["error"]) == (503, "unavailable")


# X2 ---------------------------------------------------------------------------------------------------


def test_x2_needs_the_read_scope(api, harness, platform):
    r = get(api, mint(harness, platform, OWNER_WS, {"intake.source:read"}), "signals")
    assert r.status_code == 403


def test_x2_other_workspace_is_not_found(api, harness, platform):
    r = get(
        api, mint(harness, platform, uuid.uuid4(), {"intake.x-post:read"}), "signals"
    )
    assert r.status_code == 404


def test_x2_no_token_is_401(api):
    assert api.get("/v1/x-intel/signals").status_code == 401


# X3 + X4 ----------------------------------------------------------------------------------------------


def test_x4_signals_rank_window_and_screen(api, owner_x):
    body = get(api, owner_x, "signals").json()
    assert [s["post_id"] for s in body["items"]] == [
        "1",
        "2",
        "6",
        "5",
    ]  # 3 withheld, 4 too old
    assert body["withheld"] == 1
    assert "acme" not in str(body).casefold()


def test_x4_signals_recent_order_and_filters(api, owner_x):
    recent = get(api, owner_x, "signals", order="recent").json()["items"]
    assert [s["post_id"] for s in recent] == ["5", "1", "2", "6"]
    urgent = get(api, owner_x, "signals", alert="urgent").json()["items"]
    assert [s["post_id"] for s in urgent] == ["1"]
    assert [
        s["post_id"] for s in get(api, owner_x, "signals", alert="any").json()["items"]
    ] == ["1", "2"]
    tech = get(api, owner_x, "signals", domain="D5 Technology").json()["items"]
    assert [s["post_id"] for s in tech] == ["1"]
    scored = get(api, owner_x, "signals", min_score=3).json()["items"]
    assert [s["post_id"] for s in scored] == ["2"]
    week = get(api, owner_x, "signals", since="2000-01-01T00:00:00Z", limit=10).json()[
        "items"
    ]
    assert "4" in [s["post_id"] for s in week]
    assert [
        s["post_id"] for s in get(api, owner_x, "signals", limit=1).json()["items"]
    ] == ["1"]


def test_x4_like_wildcards_are_text(api, owner_x):
    assert [
        s["post_id"] for s in get(api, owner_x, "signals", q="100%_").json()["items"]
    ] == ["6"]
    assert [
        s["post_id"] for s in get(api, owner_x, "signals", q="%").json()["items"]
    ] == ["6"]  # literal %
    assert get(api, owner_x, "signals", q="9%").json()["items"] == []


def test_x4_long_text_is_cut(api, owner_x):
    five = next(
        s for s in get(api, owner_x, "signals").json()["items"] if s["post_id"] == "5"
    )
    assert len(five["post_text"]) == x_intel.TEXT_CAP
    assert five["post_text"].endswith("…")


def test_x3_domains_window_and_mask(api, owner_x):
    body = get(api, owner_x, "domains").json()
    assert body["items"][0] == {
        "domain": "D2 Economy & Money",
        "signals": 8,
        "alerts": 2,
        "urgent": 0,
        "opportunities": 1,
        "strong_sources": 1,
    }
    assert [d["domain"] for d in body["items"]] == [
        "D2 Economy & Money",
        x_intel.WITHHELD,
    ]  # 20-day row is out
    assert body["withheld"] == 1
    assert len(get(api, owner_x, "domains", days=30).json()["items"]) == 3


def test_x4_claims_open_and_all(api, owner_x):
    body = get(api, owner_x, "claims").json()
    assert [c["claim_id"] for c in body["items"]] == ["c1"]
    assert body["withheld"] == 1
    every = get(api, owner_x, "claims", state="all").json()["items"]
    assert [c["claim_id"] for c in every] == ["c1", "c3"]


def test_x4_analyses_default_to_the_newest_week(api, owner_x):
    body = get(api, owner_x, "analyses").json()
    assert body["week"] == "2026-W45"
    assert [a["item"] for a in body["items"]] == ["TEST ai agents"]
    assert body["withheld"] == 1
    assert [
        a["item"]
        for a in get(api, owner_x, "analyses", week="2026-W44").json()["items"]
    ] == ["old"]


def test_x4_digests_and_status(api, owner_x):
    digests = get(api, owner_x, "digests").json()["items"]
    assert [d["digest_id"] for d in digests] == [
        "midday:2026-11-10",
        "morning:2026-11-10",
    ]
    assert "tokens_in" not in digests[0]
    status = get(api, owner_x, "status").json()
    assert status["signals_24h"] == 5
    assert status["open_claims"] == 2
    assert status["latest_digest"]["digest_id"] == "midday:2026-11-10"
    assert status["latest_analysis_week"] == "2026-W45"


# X5 ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("signals", {"since": "yesterday"}),
        ("signals", {"order": "random"}),
        ("signals", {"alert": "loud"}),
        ("signals", {"limit": "0"}),
        ("signals", {"limit": "201"}),
        ("signals", {"min_score": "9"}),
        ("signals", {"q": "x" * 201}),
        ("domains", {"days": "31"}),
        ("claims", {"state": "maybe"}),
        ("digests", {"limit": "abc"}),
    ],
)
def test_x5_bad_input_is_422(api, owner_x, path, params):
    assert get(api, owner_x, path, **params).status_code == 422


# X6 ---------------------------------------------------------------------------------------------------


def test_x6_reader_role_is_read_only_and_narrow(lake):
    import psycopg

    with psycopg.connect(lake, autocommit=True) as conn:
        conn.execute("SET default_transaction_read_only = on")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM x_intel.secret_stuff")
    with psycopg.connect(lake, autocommit=True) as conn:
        conn.execute("SET default_transaction_read_only = on")
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("DELETE FROM x_intel.claims")


def test_denylist_matcher():
    deny = x_intel.parse_denylist(DENY)
    assert deny == ("acme corp", "globex")
    assert x_intel.contains_term("ACME-CORP", deny)
    assert x_intel.contains_term("Ａｃｍｅ Corp", deny)  # NFKC full-width  # noqa: RUF001 - deliberate full-width letters
    assert x_intel.contains_term("a.c.m.e corp", deny)
    assert not x_intel.contains_term("acme", deny)


# MCP --------------------------------------------------------------------------------------------------


def test_mcp_x_intel_tools_read_through_the_api(api, harness, owner_x):
    import asyncio

    from cellkit.mcp import ToolFailed, build_server

    server = build_server(
        harness.cell,
        api,
        lambda: owner_x["Authorization"].removeprefix("Bearer "),
        read_only=True,
    )
    names = {t.name for t in asyncio.run(server.list_tools())}
    expected = {
        f"intake.x-intel.{n}"
        for n in ("signals", "domains", "claims", "analyses", "digests", "status")
    }
    assert expected <= names
    urgent = str(
        asyncio.run(server.call_tool("intake.x-intel.signals", {"alert": "urgent"}))
    )
    assert "https://x.com/test/status/1" in urgent
    assert "status/2" not in urgent
    assert "midday:2026-11-10" in str(
        asyncio.run(server.call_tool("intake.x-intel.status", {}))
    )
    with pytest.raises(ToolFailed):
        asyncio.run(server.call_tool("intake.x-intel.signals", {"alert": "loud"}))
    with pytest.raises(ToolFailed):
        asyncio.run(server.call_tool("intake.x-intel.status", {"workspace": "x"}))
