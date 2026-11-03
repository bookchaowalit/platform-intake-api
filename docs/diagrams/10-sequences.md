# 10 — Sequences

## 1. Generic create (เช่น `POST /v1/intakes` พร้อม `Idempotency-Key`)

```mermaid
sequenceDiagram
  participant C as Client
  participant A as intake-api
  participant P as empire-platform
  participant D as Neon intake
  C->>A: POST /v1/intakes (Bearer, Idempotency-Key)
  A->>A: verify JWT (aud intake-api), correlation id
  A->>P: POST /v1/authz/decide intake.intake:write
  P-->>A: allow
  A->>D: reserve id in create_keys (own committed txn)
  A->>P: decide again (write precheck)
  A->>D: set_config app.workspace_id
  A->>D: INSERT intakes (RLS)
  A->>P: POST /v1/executions (permission, record id, idempotency key)
  P-->>A: execution_id, replayed?, status
  alt replayed and succeeded
    A->>D: rollback
    A-->>C: existing result
  else new
    A->>D: COMMIT
    A->>P: POST /v1/executions/{id}/finish (before/after hash)
    A-->>C: 201 record
  end
  Note over A,D: UniqueViolation 409 conflict, FK 422 reference_not_found
```

Sources: `src/cellkit/app.py` (`create`, `reserve`, `write`, `audit`), `src/cellkit/platform.py`, `src/cellkit/auth.py`

## 2. Claim an intake (optimistic lock)

```mermaid
sequenceDiagram
  participant W1 as Worker 1
  participant W2 as Worker 2
  participant A as intake-api
  participant D as Neon intake
  W1->>A: PATCH /v1/intakes/{id} lease_owner w1, expected_version 1
  A->>D: SELECT ... FOR UPDATE, version = 1
  A->>D: UPDATE, version 2, COMMIT (after platform begin)
  A-->>W1: 200 version 2
  W2->>A: PATCH /v1/intakes/{id} lease_owner w2, expected_version 1
  A->>D: SELECT ... FOR UPDATE, version = 2
  A-->>W2: 409 version_conflict
```

Sources: `src/cellkit/app.py` (`update`), `tests/test_intake_queries.py::test_claiming_an_intake_bumps_the_version`

## 3. X feed push

```mermaid
sequenceDiagram
  participant G as Grok Bot collector
  participant A as intake-api
  participant P as empire-platform
  participant D as Neon intake
  G->>A: POST /v1/x-feed/pulls
  A->>P: decide intake.x-post:write (before parsing rows)
  A->>A: 413 if over 2000, validate rows, collect rejected
  A->>P: decide (write precheck)
  A->>D: upsert source x-feed, stamp last_ingested_at (lock source row)
  A->>D: upsert x_posts (newest collected_at wins)
  A->>D: insert x_sightings ON CONFLICT DO NOTHING
  A->>D: intake x-feed:pull_id landed (or reopen verified to landed) + event
  A->>D: purge exported text and sightings older than retention
  A->>P: begin execution x-post:write resource pull_id
  A->>D: COMMIT
  A->>P: finish (accepted, rejected, sightings_new)
  A-->>G: 200 counts + rejected[]
```

Sources: `src/solo_intake/x_feed.py` (`ingest`, `source_id`, `land_intake`, `purge`), `docs/x-feed-ingest.md`

## 4. Lake export mark

```mermaid
sequenceDiagram
  participant E as x_feed_lake_export.py
  participant A as intake-api
  participant D as Neon intake
  participant L as Lake (R2)
  E->>A: GET /v1/x-feed/pulls?status=landed
  E->>A: GET /v1/x-feed/pulls/{pull}/rows
  E->>L: landing JSONL, Bronze Parquet, manifest
  E->>A: POST /v1/x-feed/pulls/{pull}/exported (record_count, lake keys)
  A->>D: lock source row, lock intake row, count sightings
  alt count differs
    A-->>E: 409 pull_changed
  else same
    A->>D: intake verified + lake keys, verified event, x_posts exported_at
    A-->>E: 200 verified, posts_stamped
  end
```

Sources: `src/solo_intake/x_feed.py` (`pulls`, `pull_rows`, `exported`), `docs/x-feed-ingest.md` §4
