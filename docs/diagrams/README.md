# Core 22 SDLC diagram pack — platform-intake-api

ชุดภาพ 22 รายการตาม SDLC Diagram Catalog v2 วาดจากสิ่งที่โค้ดและ config ทำจริง ณ `origin/main` `5be3f7d` (2026-10-28). เอกสารเดิมที่ยังใช้ (reuse, ไม่ copy): [README.md](../../README.md), [PRODUCT.md](../../PRODUCT.md), [docs/x-feed-ingest.md](../x-feed-ingest.md), [docs/cellkit-notes.md](../cellkit-notes.md), [SPEC-001](../../specs/001-l2-baseline/spec.md), [SPEC-002](../../specs/002-x-feed/spec.md). Central predecessor flow pack (SQLite CLI): [lake-intake](https://github.com/bookchaowalit/architecture-docs/blob/main/docs/architecture/flows/lake-intake/README.md).

| # | Item | Status | File | Sources read |
|---|---|---|---|---|
| 01 | Business process (As-Is / To-Be) | done | [01-business-process.md](01-business-process.md) | `cell.yaml`, `app.py`, `x_feed.py`, `PRODUCT.md`, SPEC-002, central lake-intake |
| 02 | Use cases | done | [02-use-cases.md](02-use-cases.md) | `app.py`, `auth.py`, `mcp.py`, `x_feed.py`, `test_x_feed.py`, SPEC-002 |
| 03 | User flows (API call flows) | done | [03-user-flows.md](03-user-flows.md) | `app.py`, `x_feed.py`, `docs/x-feed-ingest.md`, `mcp.py`, tests |
| 04 | Traceability (RTM) | done | [04-traceability.md](04-traceability.md) | `PRODUCT.md`, SPEC-001, SPEC-002, all tests, `ci.yml`, `.railway/railway.ts` |
| 05 | C4 Context | done | [05-c4-context.md](05-c4-context.md) | `README.md`, `PRODUCT.md`, `platform.py`, `_sentry.py`, ops records |
| 06 | C4 Container | done | [06-c4-container.md](06-c4-container.md) | `Dockerfile`, `pyproject.toml`, `.railway/railway.ts`, `server.py`, `db.py`, `roles.sql` |
| 07 | C4 Component | done (flowchart) | [07-c4-component.md](07-c4-component.md) | all `src/cellkit/*.py`, `src/solo_intake/*.py` |
| 08 | ADRs | done (6, retro-documented) | [08-adr/](08-adr/) | `cell.yaml`, `Dockerfile`, `.railway/railway.ts`, migrations, `auth.py`, `platform.py`, `_sentry.py`, git log |
| 09 | ERD | done | [09-erd.md](09-erd.md) | `migrations/0001_intake.sql`, `migrations/0002_x_feed.sql`, `cell.yaml` |
| 10 | Sequences | done (4) | [10-sequences.md](10-sequences.md) | `app.py`, `platform.py`, `x_feed.py` |
| 11 | State machines | done | [11-state-machines.md](11-state-machines.md) | `cell.yaml`, `x_feed.py`, `publisher.py`, central 04-state-machine |
| 12 | API and integrations | done (reuses README API table + x-feed contract) | [12-api-integration.md](12-api-integration.md) | `app.py`, `x_feed.py`, `platform.py`, `db.py`, `mcp.py` |
| 13 | Threat model | done | [13-threat-model.md](13-threat-model.md) | `auth.py`, `app.py`, `_sentry.py`, `x_feed.py`, migrations, `roles.sql`, `gh api` rulesets |
| 14 | Backup and DR | done (backup coverage unverified) | [14-backup-dr.md](14-backup-dr.md) | `db.py`, `docs/x-feed-ingest.md`, platform-db-backup `README.md`, ops record |
| 15 | CI/CD pipeline | done | [15-cicd-pipeline.md](15-cicd-pipeline.md) | `ci.yml`, platform-ci-workflows @ `87dc5e1`, `.railway/railway.ts`, `renovate.json` |
| 16 | Deployment | done | [16-deployment.md](16-deployment.md) | `.railway/railway.ts`, `Dockerfile`, `server.py`, `README.md`, uptime `targets.ts`, ops records |
| 17 | Test coverage matrix | done | [17-test-coverage-matrix.md](17-test-coverage-matrix.md) | `tests/*.py`, `cellkit/contract.py`, `cellkit/testing.py`, `ci.yml` |
| 18 | Git / release workflow | done | [18-git-release-workflow.md](18-git-release-workflow.md) | `git log`, `gh pr list`, `gh api` rulesets, `AGENTS.md` |
| 19 | Service dependency map | done | [19-service-dependency-map.md](19-service-dependency-map.md) | `PRODUCT.md`, `pyproject.toml`, `platform.py`, `db.py`, ops records |
| 20 | Observability | done | [20-observability.md](20-observability.md) | `_sentry.py`, `app.py`, `x_feed.py`, uptime `targets.ts`, ops record |
| 21 | Incident response | done | [21-incident-response.md](21-incident-response.md) | `README.md`, `AGENTS.md`, `docs/x-feed-ingest.md`, ops records |
| 22 | DORA | done (deploy-based values not computable; 1 known incident) | [22-dora.md](22-dora.md) | `git log`, `gh run list`, `gh pr list`, ops record |

"ops record" = Claude ops memory files cited as `ops record: <file-stem> (2026-11-03)`: x-feed-intake-source, railway-deploy-approval-gate, api-gateway-edge, prod-baseline-monitoring-backups. Uptime `targets.ts` = platform-uptime-worker `src/targets.ts` @ `fe04d27`.

## Open questions รวม (ต้องการ owner)

1. `platform-event-hub-api` เขียน intake ที่นี่หรือไม่ (01, 02; `PRODUCT.md` [ต้องยืนยัน])
2. จะ enforce state transition ของ intake ใน API หรือคงไว้ที่ client (01, 11)
3. Lake export cron (`data-schedules`, D6) ขึ้นแล้วหรือยัง — ไม่มี export = ไม่มี purge (01, 14)
4. Neon `platform-intake-api` อยู่ใน nightly `ops-backups/db-backup` และ restore drill หรือไม่; RTO/RPO (14)
5. ปิด direct `*.up.railway.app` ให้ทุก client ผ่าน gateway หรือไม่ (05, 13)
6. `/docs`, `/openapi.json` เปิดสาธารณะ ตั้งใจหรือไม่; JWKS หรือ PEM ใน production (12, 16)
7. Rate limit / body-size limit และ branch protection บน `main` (13, 18)
8. `SENTRY_DSN` ตั้งจริงหรือไม่, alert rule/ช่องทาง; ใครเฝ้า `x-feed` `last_ingested_at` (20, 21)
9. Migration prod รันที่ไหน — ควรเป็น pipeline step หรือ runbook (06, 15)
10. Approve SPEC-001 / SPEC-002 และปิด review "changes requested" ของ SPEC-001 (04)
11. ใช้ Railway deployment list เป็นแหล่ง DORA หรือไม่ (22)
