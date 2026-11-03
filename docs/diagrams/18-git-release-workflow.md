# 18 — Git / release workflow

ไม่มี ruleset หรือ branch protection บน `main` (`gh api repos/bookchaowalit/platform-intake-api/rulesets` = `[]`, `branches/main` `protected: false`). ใช้ทั้ง PR (merge commit หรือ squash) และ direct commit บน `main` (Wave 2, SPEC-001 "Main-only: yes"). ไม่มี tag/release. Deploy = Railway Wait for CI บน `main`.

```mermaid
gitGraph
  commit id: "bdc1218 intake cell"
  commit id: "30d599f JWKS"
  commit id: "0714deb CI (#1 squash)"
  commit id: "056ab86 Sentry (#2-#5 squash)"
  branch docs-cd
  commit id: "5bb5aca CD docs"
  checkout main
  merge docs-cd id: "0849277 (#6)"
  branch iac-github
  commit id: "8f402b8 IaC GitHub source"
  checkout main
  merge iac-github id: "beb1142 (#7)"
  commit id: "d9dce74 L2 baseline (direct)"
  commit id: "98ddc26 numbers fix (direct)"
  commit id: "0b4ece3 SPEC-001 review"
  branch feat-x-feed
  commit id: "3cbb260 tests red"
  commit id: "8b6dd4e x-feed"
  commit id: "bec7c26 semgrep notes"
  checkout main
  merge feat-x-feed id: "7e0e04f (#8) deploy failed"
  branch fix-mcp
  commit id: "d4405a0 no mcp import"
  checkout main
  merge fix-mcp id: "5be3f7d (#9) live"
```

Sources: `git log origin/main`, `gh pr list -R bookchaowalit/platform-intake-api --state all`, `gh api .../rulesets`, `README.md`, `specs/001-l2-baseline/spec.md`, ops record: x-feed-intake-source (2026-11-03)

```mermaid
flowchart LR
  B["branch or direct commit"] --> PR{"PR?"}
  PR -->|yes| CIPR["CI on pull_request"] --> M["merge locally, push main"]
  PR -->|no, main-only| M
  M --> CIM["CI on push main"]
  CIM -->|green| RW["Railway build + NEEDS_APPROVAL"] --> HC{"/health"}
  HC -->|ok| LIVE["live"]
  HC -->|fail| OLD["previous deployment keeps serving"]
  LIVE --> V["verify /health + one authorized read (AGENTS.md)"]
```

Sources: `AGENTS.md`, `.railway/railway.ts`, `.github/workflows/ci.yml`, ops record: railway-deploy-approval-gate (2026-11-03)

## Open questions

- ต้องการ branch protection (required checks) บน `main` หรือไม่.
