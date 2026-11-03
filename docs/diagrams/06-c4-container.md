# 06 — C4 Container

```mermaid
C4Container
  title Containers - platform-intake-api
  System_Ext(clients, "Clients", "Pipelines, collector, exporter, owner, gateway")
  System_Ext(platform, "empire-platform", "authz, executions, JWKS")
  Container_Boundary(rw, "Railway project platform-intake-api") {
    Container(api, "intake-api", "Python 3.13, FastAPI, uvicorn", "cellkit app + solo_intake.x_feed extension; serverless sleep")
  }
  Container_Boundary(local, "Owner workstation") {
    Container(mcp, "intake-mcp", "Python stdio MCP", "Tools intake.resource.op + x-feed.search/top")
    Container(dbcli, "intake-db", "Python CLI", "migrate / provision via Neon API")
    Container(pub, "intake-publish", "Python CLI", "Outbox sweep; inert: no graph resources")
    Container(imp, "cellkit importer", "Python CLI", "SQLite legacy import via API")
  }
  ContainerDb(db, "Neon database intake", "PostgreSQL", "schema intake, forced RLS, roles migrator/api/publisher")
  Rel(clients, api, "HTTPS JSON")
  Rel(mcp, api, "HTTPS with caller token")
  Rel(imp, api, "HTTPS with token file")
  Rel(api, db, "intake_api role")
  Rel(dbcli, db, "intake_migrator role")
  Rel(pub, db, "intake_publisher role")
  Rel(api, platform, "decide / begin / finish")
```

Sources: `Dockerfile`, `pyproject.toml` (`[project.scripts]`), `.railway/railway.ts`, `.mcp.json`, `src/cellkit/server.py`, `src/cellkit/db.py`, `src/cellkit/publisher.py`, `src/cellkit/importer.py`, `db/roles.sql`, `migrations/0001_intake.sql`

- Image รันแค่ `intake-api` (`Dockerfile` `CMD`), ไม่มี `mcp` extra (`uv sync --no-dev`; `x_feed_mcp.py` แยกออกมาเพราะเหตุนี้).
- `.railway/railway.ts` ประกาศ service เดียว (`intake-api`); ไม่มี cron publisher. `cell.yaml` ไม่มี resource ใดประกาศ `graph` ดังนั้น outbox ไม่ถูกเขียนและ `intake-publish` ไม่มีงาน (`docs/cellkit-notes.md`).

## Open questions

- `intake-db migrate` สำหรับ prod รันจากที่ไหน/ใคร (ops record x-feed-intake-source บอกว่า owner รัน 0002 ด้วย migrator URL ในหน่วยความจำ 2026-10-28) — ควรเป็นขั้นตอนใน runbook หรือไม่.
