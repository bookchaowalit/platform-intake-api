# platform-intake-api
The Intake cell: its own API (Railway, serverless) and its own Neon
database, described by `cell.yaml` and served by the code in `src/cellkit/`, which
this repository owns. It
reuses empire-platform for identity, authorization, executions and audit over
HTTP with the caller's token.

| | |
|---|---|
| API | Railway project `platform-intake-api`, service `intake-api` (Serverless) |
| Data | Neon project `platform-intake-api`, database `intake` |
| Registry | solo-empire `repository-catalog/registries/online-systems.yaml` (`intake`) |

## API

Every resource has list, stats, get, get-by-legacy-id, create, patch and delete
(see `cellkit/app.py`). Permissions are `intake.<resource>:read|write|delete`.

| Path | Resource | Filters |
|---|---|---|
| `/v1/sources` | source | `source_key`, `status`, `domain`, `dataset`, `source_kind` |
| `/v1/intakes` | intake | `status`, `domain`, `dataset`, `source_id`, `intake_key`, `idempotency_key`, `lease_owner` |
| `/v1/intake-events` | intake-event | `intake_id`, `event_type` |
| `/v1/x-posts` | x-post | `post_id`, `author_handle` |
| `/v1/x-sightings` | x-sighting | `pull_id`, `post_id`, `requesting_chief`, `query_id`, `watch_type` |
| `/v1/x-watchlist` | x-watch | `requesting_chief`, `type`, `tag` |
| `/v1/x-query-plan` | x-query | `query_id`, `status`, `query_type` |

The X feed (source `x-feed`, pushed by the Grok Bot collector) adds batch and search routes under
`/v1/x-feed/` (`src/solo_intake/x_feed.py`): pulls, watchlist and query-plan upserts, search, top,
and the lake export rows and mark. Contract: [docs/x-feed-ingest.md](docs/x-feed-ingest.md);
change record: [specs/002-x-feed](specs/002-x-feed/spec.md).

## Develop and operate

```bash
uv sync --frozen --all-extras          # Python 3.12 (.python-version): pgserver has no cp313 wheel yet
.venv/bin/pytest -q
.venv/bin/mypy . && uvx ruff@0.17.1 check . && uvx ruff@0.17.1 format --check .   # the same checks CI runs
NEON_API_KEY=... .venv/bin/intake-db provision
npm install && railway config apply   # service settings only; code deploys from GitHub (below)
railway scale --service intake-api asia-southeast1-eqsg3a=1 us-east4-eqdc4a=0   # next to Neon and the platform
```

Dependencies are locked in `uv.lock`; the image installs them with `uv sync --frozen`, so
production runs the versions CI tested. Change a dependency with `uv add`/`uv lock` and commit
the lock. Product scope and measures: [PRODUCT.md](PRODUCT.md); change records: `specs/`.

Deploys (CD, since 2026-10-18): `intake-api` is connected to this repository's `main` with
Railway's Wait for CI (`checkSuites`). A merge to `main` deploys only after the CI and security
checks pass; a failing check leaves production on the previous deployment. Roll back by
redeploying an earlier deployment in Railway. `railway up` is no longer used.

Railway variables: `SENTRY_DSN` (error reporting; unset = off, see
`src/cellkit/_sentry.py`), `INTAKE_DB_MODE=hosted`, `INTAKE_DB_URL_API`,
`INTAKE_JWT_PUBLIC_KEY_PEM`, `INTAKE_JWT_ISSUER`, `EMPIRE_PLATFORM_URL`,
`INTAKE_X_FEED_RETENTION_DAYS` (X post text kept in Neon after export; default 180).
