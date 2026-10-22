# Product

<!-- impeccable:product-schema 1 -->

## Platform

api

## Users

- Data-lake pipelines that register sources and queue, claim, land and verify intakes:
  `data-lake-pipelines` (`infra/scripts/cli/data-intake-cli.py`, `diary-intake-cli.py`, through
  the shared `cell_store` client).
- The Solo Empire owner, through the cell's own MCP server (`intake-mcp`, `.mcp.json`) and the
  clients listed in the registry: `ops-toolkit` (`infra/scripts/utils/cell_store.py`) and
  `mcp-aggregator` (`src/cell-store.ts`, `EMPIRE_INTAKE_API`).
- Automations with an `empire-platform` token, within the permissions
  `intake.<resource>:read|write|delete`.
- Whether `platform-event-hub-api` writes intakes here: [ต้องยืนยัน]

## Product Purpose

The front door of the data lake: a registry of data sources (what they are, which domain and
dataset they feed, how private they are), a queue of intakes (one payload to land, with its
idempotency key, lease and lake result) and the event trail of every intake (queued, claimed,
lease renewed, landed, verified, rejected, failed, retried, cancelled).

Success: every payload lands once (no duplicate idempotency keys), a claimed intake has exactly
one lease owner, and every status change has an event.

## Positioning

One capability, one service: its own API (Railway), its own database (Neon) with row-level
security per workspace, and authorization, executions and audit through `empire-platform`. It is
workspace-scoped, so the same service can serve other tenants without code changes.

## Operating Context

- Production: `https://intake-api-production.up.railway.app` (`/health`), Railway project
  `platform-intake-api`, service `intake-api` (serverless, Singapore next to Neon), deployed by
  merging to `main` after CI.
- Data: Neon project `platform-intake-api`, database `intake`. 7 rows were imported from the old
  SQLite tables (`source_registry`, `intake_queue`) keeping their ids (`legacy_id`); new rows get
  ids from 1,000,000.
- Monitored by `platform-uptime-worker` (`intake-api` target); errors go to Sentry when
  `SENTRY_DSN` is set.

## Capabilities and Constraints

- Every resource has list, stats, get, get-by-legacy-id, create (with `Idempotency-Key`), patch
  (with `expected_version`) and delete:
  - `/v1/sources` (filters `source_key`, `status`, `domain`, `dataset`, `source_kind`),
  - `/v1/intakes` (filters `status`, `domain`, `dataset`, `source_id`, `intake_key`,
    `idempotency_key`, `lease_owner`),
  - `/v1/intake-events` (filters `intake_id`, `event_type`).
- Rules (covered by `tests/test_intake_*.py`):
  - a source needs `source_key` (at most 64, unique per workspace), `display_name` (160),
    `source_kind`, `domain` (80) and `dataset` (120); it starts `planned`, `private`, `manual`,
    owned by `solo_empire`, retention `operational`;
  - an intake needs `intake_key` (96, unique), `source_id`, `domain`, `dataset`, `payload_kind`,
    `input_ref` (240) and `idempotency_key` (160, unique: the same payload cannot be queued
    twice, 409); it starts `queued`, requested by `human`, with `attempt_count` 0; counts are
    never negative;
  - an event needs `intake_id`, `event_type` (one of the nine transitions) and `to_status`; its
    `actor` defaults to `system`;
  - `source_id` and `intake_id` must name a record in the same workspace (422
    `reference_not_found`); a source with intakes, or an intake with events, cannot be deleted
    (409 `has_dependents`);
  - an import (`legacy_id`) keeps its old id and a repeated import conflicts (409);
  - lists are ordered by id; `null=lease_owner` lists unclaimed intakes; stats group only by a
    declared filter; `expected_version` lets one worker win a claim (409 for the other); a patch
    that changes nothing keeps the version.
- Not enforced: that an event's `from_status`/`to_status` match the intake's real status, that
  an intake's `domain`/`dataset` match its source, or that `claimed_at` comes before
  `lease_expires_at`. The lake payloads themselves live in the data lake, not here.

## Measures

Proposed (nothing collects these yet):

- Intakes stuck in `processing` past `lease_expires_at`.
- Share of intakes ending `failed` or `rejected` per week, by source.
- 5xx rate and p95 latency on `/v1/*` (Sentry and uptime worker).
