# 09 — ERD

Schema `intake` บน Neon database `intake`. ทุกตาราง (ยกเว้น `outbox` ที่มี `id uuid` PK) ใช้ PK `(workspace_id, id)`, id เริ่ม 1,000,000, มี `legacy_id` (unique ต่อ workspace เมื่อไม่ null), `version`, `created_at`, `updated_at`; RLS forced ทุกตาราง.

```mermaid
erDiagram
  sources ||--o{ intakes : "source_id (workspace_id, id)"
  intakes ||--o{ intake_events : "intake_id (workspace_id, id)"
  x_posts ||--o{ x_sightings : "post_id (logical, no FK)"
  x_query_plan ||--o{ x_sightings : "query_id (logical, no FK)"
  intakes ||--o{ x_sightings : "intake_key = x-feed: + pull_id (logical)"

  sources {
    uuid workspace_id PK
    bigint id PK
    bigint legacy_id
    text source_key UK "<=64"
    text display_name "<=160"
    text source_kind "enum 9"
    text provider
    text domain "<=80"
    text dataset "<=120"
    text owner_scope "default solo_empire"
    text privacy_class "default private"
    text retention_class "default operational"
    text ingest_mode "default manual"
    text status "planned active paused retired"
    text description
    timestamptz last_ingested_at
    bigint version
  }
  intakes {
    uuid workspace_id PK
    bigint id PK
    text intake_key UK "<=96"
    bigint source_id FK
    text domain
    text dataset
    text schema_version "default 1"
    text payload_kind "enum 7"
    text input_ref "<=240"
    text source_batch_ref
    text idempotency_key UK "<=160"
    text privacy_class
    text retention_class
    text requested_by "human agent automation"
    text status "queued processing landed verified rejected failed cancelled"
    timestamptz requested_at
    timestamptz claimed_at
    text lease_owner
    timestamptz lease_expires_at
    int attempt_count ">=0"
    int record_count ">=0"
    text raw_sha256
    text lake_run_id
    text lake_manifest_key
    text lake_raw_object_key
    text lake_bronze_object_key
    text error_code
    text error_message
    timestamptz verified_at
    bigint version
  }
  intake_events {
    uuid workspace_id PK
    bigint id PK
    bigint intake_id FK
    text event_type "enum 9"
    text actor "default system"
    text from_status
    text to_status
    text reason
  }
  x_posts {
    uuid workspace_id PK
    bigint id PK
    text post_id UK
    text post_url
    text author_handle
    timestamptz posted_at
    text text "<=30000, purged after export"
    bigint likes
    bigint reposts
    bigint replies
    bigint views
    timestamptz first_collected_at
    timestamptz last_collected_at
    text last_pull_id
    timestamptz exported_at
    timestamptz text_purged_at
  }
  x_sightings {
    uuid workspace_id PK
    bigint id PK
    text pull_id UK "with post_id, query_id, requesting_chief"
    text post_id
    timestamptz collected_at
    text requesting_chief
    text watch_type
    text watch_value
    text query_id
    text tag
    real score
    bool top
    bigint likes
    bigint views
  }
  x_watchlist {
    uuid workspace_id PK
    bigint id PK
    text requesting_chief UK "with type, value"
    text type
    text value
    text purpose
    date added_date
    timestamptz last_used
    text tag
  }
  x_query_plan {
    uuid workspace_id PK
    bigint id PK
    text query_id UK
    text query
    text requesting_chiefs
    text tags
    int priority
    text last_since_id
    timestamptz last_run_at
    int runs
    int posts_total
    real avg_yield
    text status
    text query_type
  }
  create_keys {
    uuid workspace_id PK
    uuid actor PK
    text kind PK
    text key PK
    bigint record_id
  }
  outbox {
    uuid id PK
    uuid workspace_id
    text type
    text subject
    uuid execution_id
    jsonb payload
    timestamptz published_at
    int attempts
    timestamptz next_attempt_at
  }
```

Sources: `migrations/0001_intake.sql`, `migrations/0002_x_feed.sql`, `cell.yaml`, `db/roles.sql`

- `create_keys`: สงวน record id ต่อ (workspace, actor, kind, Idempotency-Key) ก่อนเริ่ม execution; `kind` ขยายเป็น 7 ค่าใน 0002.
- `outbox`: มีไว้สำหรับ graph events แต่ไม่มี resource ใดใน `cell.yaml` ประกาศ `graph` → ไม่มี row ถูกเขียน (`docs/cellkit-notes.md`).
- `x_sightings` แสดงเฉพาะบางคอลัมน์ (มี `reposts`, `replies` ด้วย); `x_query_plan` มีคอลัมน์สถิติเพิ่ม (`calls_total`, `new_posts_last`, `calls_last_run`, `yield_last6`, `lang_filter`, `watchlist_rows`) — ดู `cell.yaml`.
- ความสัมพันธ์ X feed เป็น logical (join ใน `x_feed.py`), ไม่มี FK ใน DB.
- Grants: `intake_api` SELECT/INSERT/UPDATE/DELETE บนตารางข้อมูล, INSERT-only บน `create_keys`; `intake_publisher` อ่าน/อัปเดตคอลัมน์ publish ของ `outbox` ผ่าน policy `publisher_sweep`.

Central ERD (เก่า, SQLite `source_registry`/`intake_queue`): https://github.com/bookchaowalit/architecture-docs/blob/main/docs/architecture/ERD-DIAGRAMS.md
