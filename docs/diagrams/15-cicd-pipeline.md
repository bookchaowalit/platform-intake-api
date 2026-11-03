# 15 — CI/CD pipeline

Workflow เดียว: `.github/workflows/ci.yml` (`CI`), เรียก reusable workflows ของ `bookchaowalit/platform-ci-workflows` pinned ที่ `87dc5e1` (v1.1.1). Public repo → GitHub-hosted `ubuntu-24.04`.

```mermaid
flowchart TB
  T1["push to main"] --> CI
  T2["pull_request"] --> CI
  T3["workflow_dispatch"] --> CI
  CI["CI (concurrency ci-ref, cancel in progress)"]
  CI --> API["job api: ci-python.yml"]
  CI --> SEC["job security: security.yml"]
  subgraph PY["ci-python.yml (python 3.12, coverage 56)"]
    P1["checkout"] --> P2["setup uv + Python"] --> P3["install (auto)"] --> P4["Ruff lint + format check"] --> P5["typecheck (mypy)"] --> P6["pytest"] --> P7["coverage gate >= 56%"]
  end
  subgraph SC["security.yml"]
    S1["gitleaks (full history)"]
    S2["semgrep p/default"]
    S3["osv-scanner"]
    S4["trivy fs HIGH,CRITICAL vuln+misconfig"]
  end
  API --> PY
  SEC --> SC
  PY --> G{"all checks green on main?"}
  SC --> G
  G -->|yes| RW["Railway Wait for CI: build Dockerfile, deploy intake-api"]
  G -->|no| STAY["production stays on previous deployment"]
  RW --> AP["since 2026-10-28: NEEDS_APPROVAL gate"]
  AP --> HC["healthcheck /health 60 s"]
  REN["Renovate: Monday before 9am, lock maintenance monthly"] --> T2
```

Sources: `.github/workflows/ci.yml`, platform-ci-workflows `ci-python.yml` / `security.yml` @ `87dc5e1`, `.railway/railway.ts`, `renovate.json`, `README.md`, ops record: railway-deploy-approval-gate (2026-11-03)

- Tests ใช้ embedded PostgreSQL (`pgserver`, dev extra) ไม่ใช่ service ของ CI (`postgres` input ไม่ได้ตั้ง), จึง pin Python 3.12 ใน CI ส่วน image เป็น 3.13 (`ci.yml` comment).
- Migration ไม่อยู่ใน pipeline: ต้องรัน `intake-db migrate` แยก (ไม่มี job/step).

## Open questions

- ควรเพิ่ม step migrate (หรือตรวจ pending migration) ก่อน deploy หรือไม่?
- NEEDS_APPROVAL gate ยังเปิดอยู่หรือไม่ ณ วันนี้.
