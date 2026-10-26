"""Sample X feed rows for the x-feed tests. Every row is clearly fake test data (handles test_*, text TEST DATA)."""

import uuid
from typing import Any

PULLS = "/v1/x-feed/pulls"
COLLECTED = "2026-10-26T06:30:00+07:00"
COLLECTOR_SCOPES = {
    "intake.x-post:read",
    "intake.x-post:write",
    "intake.x-sighting:read",
    "intake.x-watch:read",
    "intake.x-watch:write",
    "intake.x-query:read",
    "intake.x-query:write",
}

CHIEFS = ("chief-data", "chief-of-staff", "chief-opportunities", "chief-health")
TAGS = ("ai,agents", "solopreneur", "thai-tech", "health,sleep", "jobs,remote")


def post_id(n: int) -> str:
    return f"{1990000000000000000 + n}"


def row(n: int, **fields: Any) -> dict[str, Any]:
    """One x_feed row as Chief Data writes it to the sheet (all 17 columns)."""
    return {
        "collected_at": COLLECTED,
        "requesting_chief": CHIEFS[n % len(CHIEFS)],
        "watch_type": "keyword" if n % 2 else "account",
        "watch_value": f"test_value_{n % 3}",
        "post_id": post_id(n),
        "post_url": f"https://x.com/test_user_{n}/status/{post_id(n)}",
        "author_handle": f"test_user_{n}",
        "posted_at": "2026-10-25T23:00:00+00:00",
        "text": f"TEST DATA {n}: fake post about agents <script>alert(1)</script>",
        "likes": 10 * n,
        "reposts": n,
        "replies": n // 2,
        "views": 1000 + n,
        "tag": TAGS[n % len(TAGS)],
        "query_id": f"q{n % 4}",
        "score": round(0.5 + n / 100, 3),
        "top": n % 5 == 0,
        **fields,
    }


def rows(count: int = 20, start: int = 0) -> list[dict[str, Any]]:
    return [row(n) for n in range(start, start + count)]


def pull_id() -> str:
    return f"test-pull-{uuid.uuid4().hex[:8]}"


def send(
    client: Any, headers: dict[str, str], posts: list[dict[str, Any]], **body: Any
) -> Any:
    return client.post(
        PULLS,
        headers=headers,
        json={"pull_id": pull_id(), "collected_at": COLLECTED, "posts": posts, **body},
    )
