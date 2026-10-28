"""intake-mcp's x-feed tools (SPEC-002 AC-13), end to end: MCP server -> cell API -> throwaway PostgreSQL."""

import asyncio
import uuid
from typing import Any

import pytest
from x_feed_helpers import COLLECTED, COLLECTOR_SCOPES, PULLS, post_id, pull_id, rows

from cellkit.mcp import ToolFailed, build_server


def bearer(headers: dict[str, str]) -> str:
    return headers["Authorization"].removeprefix("Bearer ")


@pytest.fixture
def tools(client, harness, platform) -> tuple[Any, dict[str, str]]:
    ws = uuid.uuid4()
    collector, reader = uuid.uuid4(), uuid.uuid4()
    platform.grants[collector] = set(COLLECTOR_SCOPES)
    platform.grants[reader] = {"intake.x-post:read", "intake.x-sighting:read"}
    sent = client.post(
        PULLS,
        headers=harness.token(collector, ws),
        json={"pull_id": pull_id(), "collected_at": COLLECTED, "posts": rows(20)},
    )
    assert sent.status_code == 200, sent.text
    reader_headers = harness.token(reader, ws)
    server = build_server(
        harness.cell, client, lambda: bearer(reader_headers), read_only=True
    )
    return server, reader_headers


def call(server: Any, name: str, arguments: dict[str, Any]) -> str:
    result = asyncio.run(server.call_tool(name, arguments))
    return str(result)


def test_search_and_top_are_listed_in_read_only_mode(tools):
    server, _ = tools
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert {"intake.x-feed.search", "intake.x-feed.top", "intake.x-post.list"} <= names
    assert "intake.x-post.create" not in names


def test_search_tool_reads_through_the_api(tools):
    server, _ = tools
    found = call(server, "intake.x-feed.search", {"q": "TEST DATA 13:"})
    assert post_id(13) in found
    assert post_id(12) not in found


def test_top_tool_returns_the_best_scored_posts(tools):
    server, _ = tools
    best = call(
        server, "intake.x-feed.top", {"since": "2026-10-01T00:00:00Z", "limit": 1}
    )
    assert post_id(19) in best
    assert post_id(18) not in best


def test_tools_refuse_identity_and_unknown_arguments(tools):
    server, _ = tools
    with pytest.raises(ToolFailed):
        asyncio.run(server.call_tool("intake.x-feed.search", {"workspace_id": "x"}))
