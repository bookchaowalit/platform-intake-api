"""Read-only X intel API over the data-lake-pipelines lakehouse marts (SPEC-003).

    GET /v1/x-intel/status     newest signal, signals in the last 24 h, open claims, newest digest / analysis week
    GET /v1/x-intel/signals    ranked or newest signals (since, until, domain, alert, q, min_score, order, limit)
    GET /v1/x-intel/domains    signals, alerts, urgent and opportunities per domain over the last N days
    GET /v1/x-intel/claims     the open verification queue (or every claim)
    GET /v1/x-intel/analyses   one report week of the weekly analyses (default the newest)
    GET /v1/x-intel/digests    the Telegram digest log (ids, status, counts, cost; never message text)

The data is the owner's, not per workspace: callers need ``intake.x-post:read`` and the pinned workspace
(``INTAKE_X_INTEL_WORKSPACE``). Reads go through a read-only role (``INTAKE_X_INTEL_DB_URL``) and every row naming a
client in ``INTAKE_CLIENT_DENYLIST`` is withheld (same list and matcher as the X digest). Missing configuration fails
closed with 503. Post text is untrusted user content: returned as plain data, never interpreted.
"""

import os
import unicodedata
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, get_args

import psycopg
from fastapi import HTTPException
from fastapi import Request as HttpRequest
from fastapi.encoders import jsonable_encoder
from psycopg.rows import dict_row

from cellkit.app import Context
from cellkit.auth import Principal

S = "x_intel"
DB_ENV = "INTAKE_X_INTEL_DB_URL"
WORKSPACE_ENV = "INTAKE_X_INTEL_WORKSPACE"
DENYLIST_ENV = "INTAKE_CLIENT_DENYLIST"
MAX_LIMIT = 200
TEXT_CAP = 1000
WITHHELD = "(withheld)"
SIGNAL_COLS = (
    "post_id",
    "collected_at",
    "domain",
    "topic",
    "category",
    "signal_type",
    "alert_tier",
    "cred_tier",
    "content_label",
    "verification_status",
    "suggested_action",
    "opportunity_score",
    "priority",
    "author_handle",
    "post_url",
    "post_text",
    "likes",
    "reposts",
    "views",
)
CLAIM_COLS = (
    "claim_id",
    "claim",
    "verification_status",
    "queue_state",
    "priority",
    "next_check",
    "last_checked",
    "first_seen_link",
    "checked_by",
)
ANALYSIS_COLS = (
    "report_week",
    "analysis",
    "rank",
    "item",
    "post_id",
    "link",
    "topic",
    "book_domain",
    "geo",
    "value",
    "value_kind",
    "source_tier",
    "metric",
    "note",
)
DIGEST_COLS = (
    "digest_id",
    "kind",
    "window_start",
    "window_end",
    "status",
    "signals",
    "sent_messages",
    "cost_usd",
    "error",
    "updated_at",
)
ALERTS = {
    "any": "alert_tier IS NOT NULL AND alert_tier <> 'none'",
    "urgent": "alert_tier = 'urgent_candidate'",
    "digest": "alert_tier = 'digest'",
}


# --- configuration and denylist ------------------------------------------------------------------------


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold().strip()


def skeleton(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text.casefold()) if c.isalnum()
    )


def parse_denylist(raw: str) -> tuple[str, ...]:
    return tuple(
        normalize(t)
        for t in raw.splitlines()
        if t.strip() and not t.lstrip().startswith("#")
    )


def contains_term(text: str, denylist: Sequence[str]) -> bool:
    plain, bare = normalize(text), skeleton(text)
    return any(
        t in plain or (bool(skeleton(t)) and skeleton(t) in bare) for t in denylist
    )


def any_term(row: Mapping[str, Any], denylist: Sequence[str]) -> bool:
    return any(v is not None and contains_term(str(v), denylist) for v in row.values())


class Settings:
    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        env = environ if environ is not None else os.environ
        self.url = env.get(DB_ENV, "").strip()
        self.denylist = parse_denylist(env.get(DENYLIST_ENV, ""))
        try:
            self.workspace: uuid.UUID | None = uuid.UUID(
                env.get(WORKSPACE_ENV, "").strip()
            )
        except ValueError:
            self.workspace = None

    @property
    def ready(self) -> bool:
        return bool(self.url and self.denylist and self.workspace)


def _connect(url: str) -> psycopg.Connection[Any]:
    conn: psycopg.Connection[Any] = psycopg.connect(
        url,
        autocommit=True,
        connect_timeout=10,
        application_name="intake-x-intel",
        row_factory=dict_row,
    )
    conn.execute("SET statement_timeout = '8s'")
    conn.execute("SET default_transaction_read_only = on")
    return conn


# --- query parameters ----------------------------------------------------------------------------------


def _bad(name: str, why: str) -> HTTPException:
    return HTTPException(
        status_code=422, detail={"error": "invalid", "field": name, "reason": why}
    )


def _int(q: Mapping[str, str], name: str, default: int, lo: int, hi: int) -> int:
    raw = q.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise _bad(name, "not an integer") from None
    if not lo <= value <= hi:
        raise _bad(name, f"must be {lo}..{hi}")
    return value


def _time(q: Mapping[str, str], name: str) -> datetime | None:
    raw = q.get(name)
    if raw is None or raw == "":
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))  # noqa: FURB162
    except ValueError:
        raise _bad(name, "not an ISO 8601 time") from None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _choice(
    q: Mapping[str, str], name: str, options: Sequence[str], default: str | None
) -> str | None:
    raw = q.get(name)
    if raw is None or raw == "":
        return default
    if raw not in options:
        raise _bad(name, f"one of {', '.join(options)}")
    return raw


def _text(q: Mapping[str, str], name: str, cap: int = 200) -> str | None:
    raw = (q.get(name) or "").strip()
    if len(raw) > cap:
        raise _bad(name, f"at most {cap} characters")
    return raw or None


def _like(text: str) -> str:
    return (
        "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    )


def _cut(value: Any) -> Any:
    if isinstance(value, str) and len(value) > TEXT_CAP:
        return value[: TEXT_CAP - 1] + "…"
    return value


def _screen(
    rows: list[dict[str, Any]], denylist: Sequence[str], limit: int
) -> tuple[list[dict[str, Any]], int]:
    kept, held = [], 0
    for r in rows:
        if any_term(r, denylist):  # every field, before any cut
            held += 1
        else:
            kept.append({k: _cut(v) for k, v in r.items()})
    return kept[:limit], held


# --- routes --------------------------------------------------------------------------------------------


def register(ctx: Context, environ: Mapping[str, str] | None = None) -> None:
    cell = ctx.cell.name
    _, authenticate = get_args(ctx.caller)
    Caller = Annotated[Principal, authenticate]
    settings = Settings(environ)

    @contextmanager
    def reader(caller: Principal) -> Iterator[psycopg.Connection[Any]]:
        if not settings.ready:
            raise HTTPException(
                status_code=503, detail={"error": "x_intel_not_configured"}
            )
        ctx.allow(caller, f"{cell}.x-post:read", "x-post")
        if caller.workspace != settings.workspace:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        try:
            conn = _connect(settings.url)
        except psycopg.OperationalError as exc:
            raise HTTPException(
                status_code=503, detail={"error": "unavailable"}
            ) from exc
        try:
            yield conn
        except psycopg.Error as exc:
            raise HTTPException(
                status_code=503, detail={"error": "unavailable"}
            ) from exc
        finally:
            conn.close()

    def out(items: list[dict[str, Any]], withheld: int, **extra: Any) -> dict[str, Any]:
        encoded: dict[str, Any] = jsonable_encoder(
            {"items": items, "withheld": withheld, **extra}
        )
        return encoded

    @ctx.app.get("/v1/x-intel/signals", tags=["x-intel"])
    def signals(request: HttpRequest, caller: Caller) -> dict[str, Any]:
        q = request.query_params
        limit = _int(q, "limit", 20, 1, MAX_LIMIT)
        since = _time(q, "since") or datetime.now(UTC) - timedelta(hours=24)
        until = _time(q, "until")
        order = _choice(q, "order", ("priority", "recent"), "priority")
        alert = _choice(q, "alert", tuple(ALERTS), None)
        domain, text = _text(q, "domain", 120), _text(q, "q")
        min_score = _int(q, "min_score", 0, 0, 5) if q.get("min_score") else None
        clauses: list[str] = ["collected_at >= %s"]
        params: list[Any] = [since]
        if until:
            clauses.append("collected_at < %s")
            params.append(until)
        if domain:
            clauses.append("domain = %s")
            params.append(domain)
        if alert:
            clauses.append(ALERTS[alert])
        if text:
            clauses.append("post_text ILIKE %s")
            params.append(_like(text))
        if min_score is not None:
            clauses.append("coalesce(opportunity_score, 0) >= %s")
            params.append(min_score)
        by = (
            "priority DESC, collected_at DESC, post_id"
            if order == "priority"
            else "collected_at DESC, post_id"
        )
        with reader(caller) as conn:
            rows = conn.execute(
                # nosemgrep: python.django.security.injection.tainted-sql-string.tainted-sql-string -- clauses and order are fixed strings; every value is a %s parameter
                f"SELECT {', '.join(SIGNAL_COLS)} FROM {S}.mart_x_signal_priority WHERE {' AND '.join(clauses)}"
                f" ORDER BY {by} LIMIT %s",
                [*params, limit * 3],
            ).fetchall()
        items, held = _screen(rows, settings.denylist, limit)
        return out(items, held, since=since)

    @ctx.app.get("/v1/x-intel/domains", tags=["x-intel"])
    def domains(request: HttpRequest, caller: Caller) -> dict[str, Any]:
        days = _int(request.query_params, "days", 7, 1, 30)
        since = datetime.now(UTC) - timedelta(days=days)
        with reader(caller) as conn:
            rows = conn.execute(
                f"SELECT domain, sum(signals)::bigint AS signals, sum(alerts)::bigint AS alerts,"
                f" sum(urgent)::bigint AS urgent, sum(opportunities)::bigint AS opportunities,"
                f" sum(strong_sources)::bigint AS strong_sources"
                f" FROM {S}.mart_x_domain_hourly WHERE hour_ict >= (%s AT TIME ZONE 'Asia/Bangkok')"
                " GROUP BY domain ORDER BY signals DESC, domain",
                [since],
            ).fetchall()
        masked = 0
        for r in rows:
            if contains_term(str(r["domain"]), settings.denylist):
                r["domain"] = WITHHELD
                masked += 1
        return out(rows, masked, days=days)

    @ctx.app.get("/v1/x-intel/claims", tags=["x-intel"])
    def claims(request: HttpRequest, caller: Caller) -> dict[str, Any]:
        q = request.query_params
        limit = _int(q, "limit", 50, 1, MAX_LIMIT)
        state = _choice(q, "state", ("open", "all"), "open")
        text = _text(q, "q")
        source = f"{S}.mart_claims_queue" if state == "open" else f"{S}.claims"
        where, params = ("WHERE claim ILIKE %s", [_like(text)]) if text else ("", [])
        with reader(caller) as conn:
            rows = conn.execute(
                # nosemgrep: python.django.security.injection.tainted-sql-string.tainted-sql-string -- source and where are fixed strings; values are %s parameters
                f"SELECT {', '.join(CLAIM_COLS)} FROM {source} {where}"
                " ORDER BY priority NULLS LAST, next_check NULLS LAST, claim_id LIMIT %s",
                [*params, limit * 3],
            ).fetchall()
        items, held = _screen(rows, settings.denylist, limit)
        return out(items, held, state=state)

    @ctx.app.get("/v1/x-intel/analyses", tags=["x-intel"])
    def analyses(request: HttpRequest, caller: Caller) -> dict[str, Any]:
        q = request.query_params
        limit = _int(q, "limit", 100, 1, MAX_LIMIT)
        week = _text(q, "week", 16)
        with reader(caller) as conn:
            if not week:
                newest = conn.execute(
                    f"SELECT max(report_week) AS w FROM {S}.x_analyses"
                ).fetchone()
                week = newest["w"] if newest else None
            rows = (
                conn.execute(
                    f"SELECT {', '.join(ANALYSIS_COLS)} FROM {S}.x_analyses WHERE report_week = %s"
                    " ORDER BY analysis, rank NULLS LAST, item LIMIT %s",
                    [week, limit * 3],
                ).fetchall()
                if week
                else []
            )
        items, held = _screen(rows, settings.denylist, limit)
        return out(items, held, week=week)

    @ctx.app.get("/v1/x-intel/digests", tags=["x-intel"])
    def digests(request: HttpRequest, caller: Caller) -> dict[str, Any]:
        limit = _int(request.query_params, "limit", 10, 1, 50)
        with reader(caller) as conn:
            rows = conn.execute(
                f"SELECT {', '.join(DIGEST_COLS)} FROM {S}.digest_log ORDER BY window_end DESC, digest_id LIMIT %s",
                [limit],
            ).fetchall()
        return out(rows, 0)

    @ctx.app.get("/v1/x-intel/status", tags=["x-intel"])
    def status(caller: Caller) -> dict[str, Any]:
        with reader(caller) as conn:
            sig = conn.execute(
                f"SELECT max(collected_at) AS newest_signal,"
                f" count(*) FILTER (WHERE collected_at >= now() - interval '24 hours') AS signals_24h"
                f" FROM {S}.mart_x_signal_priority"
            ).fetchone()
            claims_open = conn.execute(
                f"SELECT count(*) AS n FROM {S}.mart_claims_queue"
            ).fetchone()
            digest = conn.execute(
                f"SELECT digest_id, status, updated_at FROM {S}.digest_log ORDER BY window_end DESC LIMIT 1"
            ).fetchone()
            week = conn.execute(
                f"SELECT max(report_week) AS w FROM {S}.x_analyses"
            ).fetchone()
        encoded: dict[str, Any] = jsonable_encoder(
            {
                **(sig or {}),
                "open_claims": (claims_open or {}).get("n", 0),
                "latest_digest": digest,
                "latest_analysis_week": (week or {}).get("w"),
            }
        )
        return encoded
