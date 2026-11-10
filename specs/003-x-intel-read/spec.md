# SPEC-003 — X intel read API (`/v1/x-intel/*`): the lakehouse marts for the owner's AIs

Standard: ADR-0004 — TDD + SDD (architecture-docs, `docs/architecture/decisions/ADR-0004-tdd-sdd-standard.md`).

## Document control

| Field | Value |
|---|---|
| Spec ID / version | SPEC-003 / 1.0 |
| Status | approved — owner chose "Agent API/MCP first" on 2026-11-10 after the X serving audit |
| Repository / path | bookchaowalit/platform-intake-api / `specs/003-x-intel-read/spec.md` |
| Owner (maker) | Claude Code (x-serving session, 2026-11-10) |
| Reviewer (checker) | Codex Stop-hook review |
| Requirement links | X serving audit 2026-11-10 gap 6: no API/MCP path to the X data; knowledge hub has none |
| Created / approved | 2026-11-10 / 2026-11-10 |

## 1. Problem and intent

- **Problem:** the X pipeline moved off `/v1/x-feed` to the data-lake-pipelines lakehouse (bot inbox → R2 raw +
  Supabase `x_intel`; docs/plans/2026-11-05-x-lakehouse.md there). Its only readers are the Telegram digest and a
  static site. The owner's AIs (Claude, Codex, MCP clients) have no API to it; the intake `x-feed` tables are empty.
- **Outcome:** read-only `GET /v1/x-intel/*` routes on this cell — already behind gateway.bookchaowalit.com and the
  MCP hub — answer from the lakehouse marts through a read-only database role, and `intake-mcp` gets typed tools.
- **Why here:** `intake` is the registered X source cell, and the owner's tokens already carry `intake.x-post:read`;
  a new cell would need new audiences, a token re-mint and gateway/MCP changes for the same reads.

## 2. Scope

| In scope | Out of scope |
|---|---|
| `GET /v1/x-intel/{status,signals,domains,claims,analyses,digests}`; client-denylist screening; workspace pin; MCP tools `intake.x-intel.*` | Writes (the bots write through the lakehouse inbox); the R2 raw lake; the watchlist/query-plan config (bot state, not insight) |

## 3. Behaviour

- **X1 Configuration, fail closed.** Needs `INTAKE_X_INTEL_DB_URL` (read-only role), `INTAKE_X_INTEL_WORKSPACE`
  (the owner workspace id) and `INTAKE_CLIENT_DENYLIST` (one term per line, same list as the digest). Any missing
  → `503 {"error": "x_intel_not_configured"}`; the database down → `503 {"error": "unavailable"}`.
- **X2 Access.** Caller needs `intake.x-post:read` (as `/v1/x-feed/search`) and must belong to the pinned workspace;
  any other workspace gets `404` (the data is the owner's, not per workspace).
- **X3 Screening.** Every returned row whose fields contain a denylist term (NFKC, case-folded, or with punctuation and
  spaces removed) is left out and counted in `withheld`; a matching domain label in `domains` is shown as
  `(withheld)`. Applied before limits are cut, so a page is never short of what the query asked for because of a
  hidden row beyond the scan window (scan = 3 × limit).
- **X4 Reads.** `signals` (since default −24 h, until, domain, alert = any|urgent|digest, q (text contains),
  min_score, order = priority|recent, limit 1–200 default 20) from `mart_x_signal_priority`; `domains` (days 1–30,
  default 7) from `mart_x_domain_hourly`; `claims` (state = open|all, q, limit) from `mart_claims_queue` / `claims`;
  `analyses` (week, default the newest) from `x_analyses`; `digests` (limit ≤ 50, screened like the rest: the error
  text can name a client) from `digest_log` (ids, status,
  counts, cost; never message text); `status` = newest signal, signals last 24 h, open claims, newest digest and
  analysis week; `freshness` = the newest timestamp per dataset with no time window (the data-sources probe).
  Text fields are cut to 1,000 characters. Post text is untrusted user content: returned as data.
- **X5 Bad input → 422**, never a 500 (dates not ISO 8601, unknown enum values, out-of-range numbers).
- **X6 Read-only all the way down.** The role `x_intel_reader` has SELECT on those six relations only,
  `default_transaction_read_only = on` and `statement_timeout = 8s`; the API opens its own short connection per request.

## 4. Tests

`tests/test_x_intel.py`, against the throwaway cluster with a fake `x_intel` schema: X1 (each env missing → 503),
X2 (no scope → 403, other workspace → 404), X3 (denylisted signal/claim withheld and counted, domain masked),
X4 (filters, order, defaults, limits, cut text), X5 (bad dates/enums/numbers → 422), MCP tool registration.
