# 05 — C4 Context

```mermaid
C4Context
  title System Context - Intake cell
  Person(owner, "Owner", "Solo Empire owner via intake-mcp, owner CLI")
  System(intake, "intake-api", "Source registry, intake queue, intake events, X feed")
  System_Ext(pipes, "data-lake-pipelines", "Intake CLIs and x_feed_lake_export.py")
  System_Ext(grok, "Grok Bot collector", "Chief Data; pushes X pulls")
  System_Ext(platform, "empire-platform", "Identity, authz decide, executions, audit, JWKS")
  System_Ext(lake, "Data lake (R2)", "Landing, Bronze social/x_feed")
  System_Ext(gw, "Edge API gateway", "gateway.bookchaowalit.com/v1/intake")
  System_Ext(mcphub, "MCP aggregator / remote MCP hub", "Cell tools for AIs")
  System_Ext(uptime, "Uptime worker", "Hourly /health probe")
  System_Ext(sentry, "Sentry", "Errors when SENTRY_DSN set")
  SystemDb_Ext(neon, "Neon platform-intake-api", "PostgreSQL database intake")

  Rel(owner, intake, "REST / MCP", "HTTPS bearer")
  Rel(owner, gw, "owner CLI client.env")
  Rel(gw, intake, "Proxies /v1/intake")
  Rel(mcphub, gw, "Cell calls")
  Rel(pipes, intake, "Queue, claim, land, export", "HTTPS")
  Rel(grok, intake, "POST /v1/x-feed/pulls", "HTTPS")
  Rel(pipes, lake, "Writes payloads")
  Rel(intake, platform, "decide, executions, finish, JWKS", "HTTPS")
  Rel(intake, neon, "SQL under RLS", "TLS")
  Rel(uptime, intake, "GET /health")
  Rel(intake, sentry, "Error events")
```

Sources: `README.md`, `PRODUCT.md`, `src/cellkit/platform.py`, `src/cellkit/auth.py`, `src/cellkit/_sentry.py`, `docs/x-feed-ingest.md`, `src/cellkit/mcp.py`, ops record: api-gateway-edge (2026-11-03), ops record: prod-baseline-monitoring-backups (2026-11-03), uptime `src/targets.ts`

หมายเหตุ: cell เองไม่คุยกับ lake หรือ X; client (pipelines, Grok Bot) เป็นฝ่ายคุย. Gateway เป็นทางหนึ่ง แต่ `*.up.railway.app` ยังเปิดตรง (README, uptime target, `docs/x-feed-ingest.md` base URL).

## Open questions

- จะให้ทุก client ผ่าน gateway แล้วปิด direct `intake-api-production.up.railway.app` หรือไม่ (collector contract ยังชี้ direct URL).
