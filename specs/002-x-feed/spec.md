# SPEC-002 — X feed source (`x-feed`): batch ingest, collector state, search, lake export

Standard: ADR-0004 — TDD + SDD (architecture-docs, `docs/architecture/decisions/ADR-0004-tdd-sdd-standard.md`).
Contract for the collector: [docs/x-feed-ingest.md](../../docs/x-feed-ingest.md).

## Document control

| Field | Value |
|---|---|
| Spec ID / version | SPEC-002 / 1.0 |
| Status | in review (implemented on branch `feat/x-feed-source`; owner approval pending) |
| Repository / path | bookchaowalit/platform-intake-api / `specs/002-x-feed/spec.md` |
| Owner (maker) | Claude Code (x-feed session, 2026-10-26) |
| Reviewer (checker) | independent reviewer subagent (no maker context) |
| Approver | Owner (bookchaowalit): pending |
| Requirement links | Owner brief 2026-10-26 "add an `x-feed` source to my intake cell"; solo-empire `data-sources.yaml` `x-feed` |
| Main-only | no: PR branch; the red run is commit `3cbb260` |
| Created / approved | 2026-10-26 / pending owner |

## 1. Problem and intent

- **Problem:** X is the only data source outside the central system. The Grok Bot collector (Chief
  Data) writes X posts, its watchlist and its query plan to a Google Sheet, so the owner's other AIs
  (Claude, Codex, Gemini, Copilot) cannot read one shared copy and nothing reaches the lake.
- **Outcome:** the collector pushes each pull to the intake cell over HTTPS with a token that reaches
  only the X feed; posts are deduplicated, every pull is an intake-queue row with the usual trail and
  freshness probe, the owner's AIs read it through REST and `intake-mcp`, and a lake adapter lands it
  in Bronze `social/x_feed`.
- **Why now:** the owner's central-system review (2026-10-26) found X as the one missing collector.

## 2. Scope

| In scope | Out of scope (non-goals) |
|---|---|
| Resources `x-post`, `x-sighting`, `x-watch`, `x-query` (migration 0002); batch ingest; watchlist and query-plan upserts; search/top; pull export rows and the exported mark; retention on ingest; `mcp_extend` hook with two tools | Calling X itself (the Grok Bot does); the scheduled host for the lake export (owner decision D6: a Railway cron, owner action); retiring the sheet (after a parallel run) |

## 3. Behaviour — scenarios

All tests: level integration (API + throwaway PostgreSQL + fake platform), in `tests/test_x_feed.py`
unless named.

| AC | Given / when / then | Test |
|---|---|---|
| AC-01 | A pull of 20 rows lands 20 posts, 20 sightings and one `landed` intake (`x-feed:<pull_id>`, dataset `x_feed`) with one `landed` event | `test_a_pull_lands_posts_sightings_and_an_intake_row` |
| AC-02 | The first push registers source `x-feed` (api, active) and every push stamps `last_ingested_at` | `test_the_source_is_registered_and_its_last_ingest_is_stamped` |
| AC-03 | Re-sending the same pull adds nothing; one post seen by two queries is one post, two sightings; a later pull refreshes metrics, an older re-send does not roll them back | `test_resending_the_same_pull_duplicates_nothing`, `test_the_same_post_from_two_queries_is_one_post_and_two_sightings`, `test_a_later_pull_refreshes_metrics_and_keeps_first_collected`, `test_an_older_resend_does_not_roll_metrics_back` |
| AC-04 | Unknown, missing or invalid row fields reject that row only, with index, fields and reason; a pull with no valid row is 422 `no_valid_rows` | `test_bad_rows_are_reported_and_good_rows_still_land`, `test_a_pull_with_no_valid_row_is_refused` |
| AC-05 | More than 2,000 posts is 413; unknown top-level keys and bad `pull_id`s are 422 | `test_more_than_2000_posts_is_refused`, `test_unknown_top_level_fields_and_bad_pull_ids_are_refused` |
| AC-06 | Sheet-style values are normalised (numeric `post_id`, `@handle`, `"1,234"`, `"TRUE"`, tag lists, empty `query_id` → `-`, X date format, NUL bytes); text is stored as given | `test_sheet_style_values_are_normalised`, `test_post_text_is_stored_as_given_not_rendered` |
| AC-07 | The collector scopes cannot read or write sources or intakes; ingest needs `intake.x-post:write`; no token is 401 | `test_the_collector_token_cannot_touch_the_rest_of_intake`, `test_ingest_needs_the_x_post_write_permission` |
| AC-08 | Pulls stay inside their workspace (RLS) | `test_pulls_stay_inside_their_workspace` |
| AC-09 | Watchlist upserts on (chief, type, value), query plan on `query_id` | `test_watchlist_upsert_is_idempotent_on_chief_type_value`, `test_query_plan_upsert_keeps_one_row_per_query` |
| AC-10 | Search by text (wildcards literal), tag, chief; top orders by score; both need read permission | `test_search_by_text_tag_and_chief`, `test_search_treats_like_wildcards_as_text`, `test_top_orders_by_score`, `test_search_needs_read_permission` |
| AC-11a | The exporter's scopes (x-post read, x-sighting read/write) list and mark pulls and get 403 on `/v1/intakes` and `/v1/sources` | `test_the_exporter_scopes_reach_only_x_feed_pulls` |
| AC-11 | Export rows carry all 17 sheet columns plus `sighting_key`; marking sets the intake `verified` with lake keys and stamps posts; a changed pull is 409 `pull_changed`; new rows reopen a verified pull; the collector cannot mark; unknown pull 404 | `test_export_rows_then_mark_the_pull_verified`, `test_marking_a_pull_that_changed_since_the_read_is_refused`, `test_new_rows_after_export_put_the_pull_back_to_landed`, `test_the_collector_cannot_mark_exports`, `test_an_unknown_pull_is_not_found` |
| AC-12 | Ingest clears text and deletes sightings of exported posts older than the retention window; unexported posts, and posts in a pull not yet exported (a backfill), keep their text | `test_exported_text_older_than_the_retention_window_is_purged`, `test_a_backfill_never_purges_text_the_lake_does_not_have` |
| AC-12a | `collected_at` needs an offset and cannot be in the future; a reader is refused before its rows are parsed; a partial query-plan row keeps stored values | `test_collection_times_need_an_offset_and_cannot_be_in_the_future`, `test_a_reader_is_refused_before_its_rows_are_parsed`, `test_a_partial_query_plan_row_keeps_the_stored_values` |
| AC-13 | `intake-mcp` lists `intake.x-feed.search` and `.top` in read-only mode, they read through the API, and refuse unknown arguments | `tests/test_x_feed_mcp.py` (4 tests) |
| AC-14 | The generic CRUD, authorization, isolation and idempotency contract holds for the four new resources | `tests/test_contract.py` (kit suite, parametrised per resource) |

## 4. Interfaces and data

| Interface | Change | Contract |
|---|---|---|
| `POST /v1/x-feed/pulls`, `PUT /v1/x-feed/watchlist`, `PUT /v1/x-feed/query-plan` | new | `docs/x-feed-ingest.md` |
| `GET /v1/x-feed/search`, `/top`, `/pulls?status=`, `/pulls/{id}/rows`; `POST /v1/x-feed/pulls/{id}/exported` (`intake.x-sighting:write`) | new | same |
| `/v1/x-posts`, `/v1/x-sightings`, `/v1/x-watchlist`, `/v1/x-query-plan` | new generic resources | README |
| `cell.yaml` `mcp_extend` | new kit hook (`cellkit.mcp.Extension`) | `src/cellkit/mcp.py` |

- **Data model / migration:** `migrations/0002_x_feed.sql` adds four tables (RLS forced, API grants)
  and widens `create_keys_kind_check`. Additive only; no existing row changes.
- **Permissions (empire-platform):** `intake.x-post|x-sighting|x-watch|x-query:read|write|delete` in
  `INTAKE_OWNER`; automations `x-feed-collector` and `x-feed-lake-export`; x-feed scopes for
  `owner-mcp` and `reporting-reader` (platform-empire PR).
- **Backward compatibility:** no existing route or payload changes.

## 5. Non-functional requirements

| NFR | Target | How it is tested |
|---|---|---|
| Performance | a 2,000-row pull is three set-based statements (posts, sightings, intake), not per-row | code review; local e2e |
| Security / privacy | collector token reaches only the X feed; X text is untrusted, stored as text, never rendered; errors never echo row content | AC-07, AC-08, AC-06 |
| Reliability | every push is idempotent; export never loses rows (409 on a changed pull) | AC-03, AC-11 |
| Retention | Neon text ≤ 180 days (`INTAKE_X_FEED_RETENTION_DAYS`), only after export | AC-12 |
| Cost | no new service or paid tier in this change | — |

## 6. Test plan (TDD) and evidence

- **Test data:** generated fake rows (`tests/x_feed_helpers.py`: handles `test_user_*`, text `TEST DATA`).
- **Red:** `3cbb260` (tests only) · `.venv/bin/pytest -q tests/test_x_feed.py tests/test_x_feed_mcp.py`
  → `25 failed, 2 passed, 4 errors` (routes 404/405, `mcp` tools missing). The 2 that passed were the
  401 and 403 checks, which hold without the routes too.
- **Green (local, 2026-10-26):** `.venv/bin/pytest -q` → 161 passed, 35 skipped; `mypy .` clean; Ruff
  check and format clean. CI on the PR is the authoritative run.
- **Local end-to-end (2026-10-26, loopback only):** intake app on 127.0.0.1 (throwaway PostgreSQL, fake
  platform, throwaway key) ← `curl --data-binary @docs/examples/x-feed-sample-pull.json` twice (20 new,
  then 20 duplicates) → collector token on `/v1/sources` 403 → `x_feed_lake_export.py` (data-lake-pipelines)
  wrote 20 rows to a local Bronze part and marked the pull `verified` → `/v1/x-feed/top` read back. Re-run
  after the scope narrowing below: collector and exporter tokens both 403 on `/v1/intakes`; export still
  20 rows, pull `verified`; search read back.
- **Not verified:** anything hosted (Neon migration, Railway deploy, real tokens, R2). See §7.

### Review triage (2026-10-26)

- Automated security review (commit hook): the exporter held `intake.intake:read|write`, a right over every
  source's intake rows. **Fixed:** new `GET /v1/x-feed/pulls`; the exported mark needs `intake.x-sighting:write`;
  the exporter holds only `intake.x-*` (platform test pins it; the collector lacks x-sighting:write).
- Independent reviewer (`solo:solo-reviewer`, read-only, no maker context): approved, 0 blocking, 9 non-blocking.
  Fixed: authorize before parsing rows; lock order (every x-feed write takes the source row first, rows sorted),
  which also closes the first-send race; `collected_at` offset and not-in-future; purge skips posts in an
  unexported pull; partial state rows keep stored values; NUL in list values. Not done (by choice): explicit
  `workspace_id` predicates on top of forced RLS (the kit relies on RLS the same way); a trigram index for
  `q` (add when the table grows); an ingress body-size limit; checking `resource_type` against the real
  platform (now `x-post`/`x-sighting`, matching the permission names; verify with one real call after deploy).

## 7. Risks and open questions

| # | Risk or question | Impact | Owner | Resolution / date |
|---|---|---|---|---|
| 1 | The weekly token-rotate cron cannot push into the Grok Bot | collector stops after 30 days | owner | rotate by hand on `token_expiring`; documented |
| 2 | The lake export has no scheduled host yet | pulls stay `landed`; text is never purged (purge waits for export) | owner | Railway cron in `data-schedules` (D6), owner approval |
| 3 | The collector's real `x_feed` values may differ from the sheet headers' implied types | rows rejected with reasons | Chief Data | parallel run with the sheet before retiring it |

## 8. Change log

| Version | Date | Change | Scenarios affected | Approved by |
|---|---|---|---|---|
| 1.0 | 2026-10-26 | Implemented on `feat/x-feed-source` | all | pending owner |
