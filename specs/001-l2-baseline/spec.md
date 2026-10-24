# SPEC-001 — L2 baseline: locked dependencies, strict types, domain rules under test

Standard: ADR-0004 — TDD + SDD (architecture-docs, `docs/architecture/decisions/ADR-0004-tdd-sdd-standard.md`).
Big Loop Plan Wave 2 (solo-empire `repository-catalog/roadmaps/BIG-LOOP-PLAN-2026-10-21.md`).

## Document control

| Field | Value |
|---|---|
| Spec ID / version | SPEC-001 / 1.0 |
| Status | in review (implemented; owner approval pending) |
| Repository / path | bookchaowalit/platform-intake-api / `specs/001-l2-baseline/spec.md` |
| Owner (maker) | Claude Code (Wave 2 cells session) |
| Reviewer (checker) | Fresh Claude reviewer session (no maker context) |
| Approver | Owner (bookchaowalit): pending, see the Wave 2 report owner actions |
| Requirement links | Big Loop DoD L2: `PRODUCT.md`, ≥ 3 test files, Sentry, type check; L1 lockfile |
| Main-only | yes: committed straight to `main`, so the red run is local (ADR-0004 rule 2, v1.1) |
| Created / approved | 2026-10-22 / pending owner |

## 1. Problem and intent

- **Problem:** Dependencies were installed unpinned, there was no type check, and the only tests were the generic contract suite; nothing tested the intake cell's own rules (enums, key limits, unique source and idempotency keys, source and intake references, lease claims).
- **Outcome:** the image installs exactly `uv.lock` (`uv sync --frozen`), CI runs Ruff, mypy
  (strict on `src/`) and a coverage gate on shared CI v1.1.1, and the cell's own rules have
  tests of their own beyond the generic contract suite.
- **Why now:** Wave 2 of the Big Loop Plan; milestone M1 is 2026-11-15.

## 2. Scope

| In scope | Out of scope (non-goals) |
|---|---|
| `uv.lock`, Dockerfile, CI caller bump, Ruff/mypy config and fixes, domain tests, `PRODUCT.md` | New endpoints or fields; database migrations; a shared cellkit package (owner decision 2026-10-21: each service owns its code) |

## 3. Behaviour — scenarios

### AC-01 — Source kind must be a known kind

- **Given** an owner with write permission
- **When** they register a source with `source_kind` ftp
- **Then** the API answers 422; webhook is accepted
- **Test:** `tests/test_intake_validation.py::test_source_kind_must_be_a_known_kind` · level: integration (API + throwaway PostgreSQL)

### AC-02 — An intake cannot point at a missing or foreign source

- **Given** a source in another workspace
- **When** the owner queues an intake with that `source_id`, or with an id that does not exist
- **Then** the API answers 422 `reference_not_found`
- **Test:** `tests/test_intake_validation.py::test_an_intake_cannot_point_at_another_workspaces_source` · level: integration (API + throwaway PostgreSQL)

### AC-03 — The same payload cannot be queued twice

- **Given** an intake with `idempotency_key` sha-abc
- **When** another intake with the same key is queued
- **Then** the API answers 409 and only one intake has that key
- **Test:** `tests/test_intake_defaults.py::test_the_same_payload_cannot_be_queued_twice` · level: integration (API + throwaway PostgreSQL)

### AC-04 — Source keys are unique per workspace

- **Given** a source `bank-kbank`
- **When** the same key is registered again in the workspace, then in another workspace
- **Then** the first is refused with 409, the second is created
- **Test:** `tests/test_intake_defaults.py::test_source_key_is_unique_within_a_workspace` · level: integration (API + throwaway PostgreSQL)

### AC-05 — New intakes are queued by a human with no attempts

- **Given** an intake with only its required fields
- **When** it is created
- **Then** `status` is queued, `requested_by` human, `attempt_count` 0, `schema_version` "1", `privacy_class` private
- **Test:** `tests/test_intake_defaults.py::test_new_intake_is_queued_by_a_human_with_no_attempts` · level: integration (API + throwaway PostgreSQL)

### AC-06 — A source with intakes cannot be deleted

- **Given** a source with one intake
- **When** the owner deletes the source
- **Then** the API answers 409 `has_dependents`
- **Test:** `tests/test_intake_defaults.py::test_a_source_with_intakes_cannot_be_deleted` · level: integration (API + throwaway PostgreSQL)

### AC-07 — Only one worker wins a claim

- **Given** a queued intake at version 1
- **When** worker-1 claims it with `expected_version` 1, then worker-2 tries with `expected_version` 1
- **Then** the first is version 2 with lease owner worker-1; the second gets 409 and the lease stays with worker-1
- **Test:** `tests/test_intake_queries.py::test_claiming_an_intake_bumps_the_version` · level: integration (API + throwaway PostgreSQL)

### AC-08 — Stats count intakes per status and refuse non-filters

- **Given** two queued and one failed intake
- **When** the owner asks for stats by `status`, then by `payload_kind`
- **Then** the groups are queued 2, failed 1; grouping by `payload_kind` is refused with 422
- **Test:** `tests/test_intake_queries.py::test_stats_count_intakes_per_status` · level: integration (API + throwaway PostgreSQL)

### AC-09 — Numbers fit their columns

- **Given** an int field (PostgreSQL integer) or a real field
- **When** a client sends 2**31, or NaN / Infinity / 1e400 as raw JSON
- **Then** the API answers 422 naming the field (before: a 500 from PostgreSQL, or the value silently stored as null)
- **Test:** `tests/test_contract.py::test_numbers_fit_their_columns` · level: integration (API + throwaway PostgreSQL)

## 4. Interfaces and data

| Interface | Change | Contract |
|---|---|---|
| `/v1/*` (all resources) | unchanged | same routes and payloads; see README |

- **Data model / migration:** N/A — no schema change. Range rules are checked by the API on
  create and update; rows already stored are not rewritten.
- **Backward compatibility:** clients keep the same routes. A write that would store a range
  ending before it starts now gets `422 invalid_value` instead of `201/200`.

## 5. Non-functional requirements

| NFR | Target | How it is tested |
|---|---|---|
| Performance | N/A — no hot-path change beyond one comparison per declared range | — |
| Security / privacy | Same authorization, RLS and Sentry scrubbing as before | contract suite (`tests/test_contract.py`), `tests/test_sentry.py` |
| Reliability / observability | Reproducible image from `uv.lock`; failed inline publishes reach Sentry | image rehearsal before push; `test_inline_publish_failure_is_reported` |
| Accessibility / UX | N/A — API only | — |

## 6. Test plan (TDD)

- **Test levels:** integration tests against the FastAPI app with a throwaway local PostgreSQL
  (pgserver) and a fake platform; no hosted database or platform.
- **Test data:** generated in each test; no production data.
- **Coverage:** CI gate `coverage-threshold: "56"` (measured 58.50% on 2026-10-22, minus 2 points).
- **Not test-first (exceptions):** tests that pin behaviour the service already had
  (characterization tests, marked below) were written after the code by nature; tooling and
  config changes are covered by CI itself.

### Red / green log

| Scenario | Test | Red: commit / run + failure message | Green: commit / run | Refactor note |
|---|---|---|---|---|
| AC-01 | `tests/test_intake_validation.py::test_source_kind_must_be_a_known_kind` | characterization (behaviour already present; passed on first run) | CI run of the pushed tip | none |
| AC-02 | `tests/test_intake_validation.py::test_an_intake_cannot_point_at_another_workspaces_source` | characterization (behaviour already present; passed on first run) | CI run of the pushed tip | none |
| AC-03 | `tests/test_intake_defaults.py::test_the_same_payload_cannot_be_queued_twice` | characterization (behaviour already present; passed on first run) | CI run of the pushed tip | none |
| AC-04 | `tests/test_intake_defaults.py::test_source_key_is_unique_within_a_workspace` | characterization (behaviour already present; passed on first run) | CI run of the pushed tip | none |
| AC-05 | `tests/test_intake_defaults.py::test_new_intake_is_queued_by_a_human_with_no_attempts` | characterization (behaviour already present; passed on first run) | CI run of the pushed tip | none |
| AC-06 | `tests/test_intake_defaults.py::test_a_source_with_intakes_cannot_be_deleted` | characterization (behaviour already present; passed on first run) | CI run of the pushed tip | none |
| AC-07 | `tests/test_intake_queries.py::test_claiming_an_intake_bumps_the_version` | characterization (behaviour already present; passed on first run) | CI run of the pushed tip | none |
| AC-08 | `tests/test_intake_queries.py::test_stats_count_intakes_per_status` | characterization (behaviour already present; passed on first run) | CI run of the pushed tip | none |
| AC-09 | `tests/test_contract.py::test_numbers_fit_their_columns` | 841efd1 · `.venv/bin/pytest -q -k numbers_fit` · `psycopg.errors.NumericValueOutOfRange: integer out of range` | CI run of the pushed tip | none |

## 7. Risks and open questions

| # | Risk or question | Impact | Owner | Resolution / date |
|---|---|---|---|---|
| 1 | Stored rows written before a range rule existed may already be inverted | a patch touching one of those dates is refused until both are fixed | owner | patches that do not touch the range still work |

## 8. Change log

| Version | Date | Change | Scenarios affected | Approved by |
|---|---|---|---|---|
| 1.0 | 2026-10-22 | Implemented with the Wave 2 baseline | all | pending owner |

## Approval

| Gate | Role | Name / date | Decision | Evidence |
|---|---|---|---|---|
| Implemented (DoD) | Reviewer (checker) | Fresh Claude reviewer / 2026-10-22 | see Wave 2 report | CI run of the pushed tip |
| Implemented (DoD) | Approver | Owner | pending | Wave 2 report |

## Review (2026-10-24): changes requested

Checker: independent Claude reviewer subagent (`solo:solo-reviewer`, Sonnet, read-only, no maker context). Status unchanged until fixed.

- Tests run by the checker: .venv/bin/pytest -q: 91 passed, 13 skipped
- Gap: Range risk row and range wording are false (no `ranges` in cell.yaml). Remove the template residue.
