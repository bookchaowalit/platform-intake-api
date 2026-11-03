# 03 — User flows (API call flows per role)

API only ไม่มีหน้า UI (`PRODUCT.md` Platform: api) ดังนั้น "flow" คือลำดับ call ของแต่ละ role.

## Pipeline: queue → claim → land → verify

```mermaid
flowchart TD
  A["GET /v1/sources?source_key=..."] --> B{"found?"}
  B -->|no| C["POST /v1/sources (Idempotency-Key)"]
  B -->|yes| D["POST /v1/intakes (idempotency_key unique)"]
  C --> D
  D -->|"409 conflict"| D2["Already queued: GET /v1/intakes?idempotency_key=..."]
  D --> E["GET /v1/intakes?null=lease_owner&status=queued"]
  E --> F["PATCH /v1/intakes/{id} lease_owner + expected_version"]
  F -->|"409 version_conflict"| E
  F --> G["Land payload in lake (client side)"]
  G --> H["PATCH status landed / verified + lake keys"]
  H --> I["POST /v1/intake-events"]
```

Sources: `src/cellkit/app.py` (list `null=` filter, `expected_version`, `Idempotency-Key`), `tests/test_intake_queries.py`, `tests/test_intake_defaults.py`, `PRODUCT.md`

## Collector: push a pull

```mermaid
flowchart TD
  S["GET /v1/x-query-plan, /v1/x-watchlist (read state)"] --> P["Collect from X (outside this cell)"]
  P --> Q["POST /v1/x-feed/pulls (<= 2000 posts)"]
  Q -->|"413 batch_too_large"| Q2["Split, same pull_id"]
  Q2 --> Q
  Q -->|"200 with rejected[]"| F["Fix rejected rows, resend same pull_id"]
  Q -->|"503"| B["Backoff 30 s / 2 min / 10 min, resend"]
  Q --> U["PUT /v1/x-feed/query-plan, /v1/x-feed/watchlist"]
```

Sources: `docs/x-feed-ingest.md`, `src/solo_intake/x_feed.py`

## Exporter: lake export

```mermaid
flowchart TD
  L["GET /v1/x-feed/pulls?status=landed"] --> R["GET /v1/x-feed/pulls/{pull}/rows"]
  R --> W["Write landing JSONL + Bronze Parquet + manifest (data-lake-pipelines)"]
  W --> M["POST /v1/x-feed/pulls/{pull}/exported (record_count, lake keys)"]
  M -->|"409 pull_changed"| L
  M -->|"200 verified"| D["Done"]
```

Sources: `docs/x-feed-ingest.md` §4, `src/solo_intake/x_feed.py` `pulls`, `pull_rows`, `exported`

## Owner / AI: read

```mermaid
flowchart LR
  O["intake-mcp tool or REST"] --> T{"tool"}
  T -->|"intake.x-feed.search"| S1["GET /v1/x-feed/search"]
  T -->|"intake.x-feed.top"| S2["GET /v1/x-feed/top"]
  T -->|"intake.resource.list/get"| S3["GET /v1/plural"]
  T -->|"create/update/delete (not in READONLY)"| S4["POST / PATCH / DELETE"]
```

Sources: `src/cellkit/mcp.py`, `src/solo_intake/x_feed_mcp.py`, `.mcp.json`, `AGENTS.md`

## Open questions

- client ฝั่ง pipeline ทำ claim/land/verify ตามลำดับนี้จริงหรือไม่ (โค้ด client อยู่ data-lake-pipelines / ops-toolkit ไม่ได้อ่านใน pack นี้).
