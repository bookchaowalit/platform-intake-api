# 21 — Incident response

ไม่มี runbook ใน repo; flow นี้ประกอบจาก alert channel และขั้นตอนที่ `README.md` / `AGENTS.md` / `docs/x-feed-ingest.md` ระบุ.

```mermaid
flowchart TD
  A1["Uptime worker: intake-api down (Telegram)"] --> T
  A2["Sentry error (if DSN set)"] --> T
  A3["Client sees 503 unavailable / authorization_unavailable"] --> T
  A4["empire-monitor token_expiring (collector)"] --> TK["Mint x-feed-collector token, replace in Grok Bot"]
  T["Triage: which dependency?"] --> D1{"/health ok?"}
  D1 -->|no| R1["Railway: deployment state, logs; NEEDS_APPROVAL?"]
  R1 --> R2["Rollback: redeploy earlier deployment in Railway"]
  D1 -->|yes| D2{"503 unavailable?"}
  D2 -->|yes| N1["Neon: compute / quota / connection URL"]
  D2 -->|no| D3{"503 authorization_unavailable or 401?"}
  D3 -->|yes| P1["empire-platform health, grants, token audience"]
  D3 -->|no| F1["Bug: failing test first (ADR-0004), fix on branch"]
  F1 --> F2["CI green, merge main, Wait for CI deploy"]
  R2 --> V["Verify /health + one authorized read"]
  N1 --> V
  P1 --> V
  F2 --> V
  V --> PM["Postmortem: ops record / spec risk table (no template in repo)"]
```

Sources: `README.md` (rollback), `AGENTS.md` (verify after merge, failing test first), `src/cellkit/app.py` (503/401 codes), `docs/x-feed-ingest.md` (Errors, Token), ops record: prod-baseline-monitoring-backups (2026-11-03), ops record: railway-deploy-approval-gate (2026-11-03)

## เหตุการณ์ที่บันทึกไว้

| Date | What | Resolution | Source |
|---|---|---|---|
| 2026-10-28 | `7e0e04f` (#8) deploy fail healthcheck: `x_feed.py` import `cellkit.mcp`, image ไม่มี `mcp` extra | #9 `5be3f7d` แยก MCP tools ไป `x_feed_mcp.py`; prod อยู่บน deploy เดิมระหว่างนั้น | ops record: x-feed-intake-source; `tests/test_x_feed_mcp.py::test_api_hook_loads_without_the_mcp_extra` |
| 2026-10-28 → 11-03 | owner-mcp ได้ 403 จาก intake: owner role ขาด 12 `intake.x-*` permissions (grant ถูกบล็อกโดย Neon quota ของ empire-platform) | `empire_platform.cells grant --workspace owner --cell intake` 2026-11-03 | ops record: api-gateway-edge |

## Open questions

- Sentry alert rule และช่องทางของ intake-api.
- ต้องการ runbook / postmortem template ใน repo หรือใช้ ops record ต่อ.
