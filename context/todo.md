# Implementation Checklist

Each module includes its API, UI where applicable, migrations, and tests. Complete its test gate before dependent modules. Modules sharing completed prerequisites may proceed independently.

## M0 — Compose Foundation · v0.1

- [x] Define service contracts, configuration, and database volume ownership.
- [x] Add Compose services: `web` (nginx + built frontend), `api`, and `db`.
- [x] Configure private services, persistent database volume, health checks, migrations, and local HTTPS.
- [x] Add Python/frontend test tooling and repeatable Compose test commands.
- [x] **Test:** clean startup, migrations, health checks, restart persistence, private service ports.

## M1 — Sandbox Runner · v0.2 · requires M0

- [ ] Add the `judge` Compose service and image with isolate.
- [ ] Prove isolate/cgroup v2 operation inside `judge` on target Linux; document required permissions/mounts.
- [ ] Add separate compilation, execution, checker, and generator profiles.
- [ ] Implement runner input/output contract, limits, verdict mapping, and cleanup.
- [ ] **Test:** valid C, compile errors, crashes, time/memory/output limits, blocked fork/network/answer access, clean state per case.
- [ ] **Gate:** no submission execution until container isolation tests pass.

## M2 — Identity · v0.2 · requires M0

- [ ] Add admin/student sessions, password hashing, CSRF, and rate limits.
- [ ] Add CSV import, credentials sheet, password reset, and audit records.
- [ ] **Test:** role separation, session revocation, malformed/duplicate imports, protected routes.

## M3 — Task Library · v0.2 · requires M0, M2

- [ ] Add tasks with optional Markdown statements, immutable revisions, ZIP/pasted cases.
- [ ] Implement exact/token checker contracts and scoring configuration.
- [ ] Add draft validation and publish/review screens.
- [ ] **Test:** optional/safe Markdown, malformed archives, traversal/size limits, checker edge cases, revision immutability, protected files.

## M4 — Labs and Binding · v0.3 · requires M2, M3

- [ ] Add scheduling, enrollment, ordered tasks, and server countdown.
- [ ] Add multiple lab PDF uploads, protected downloads, and dashboard links.
- [ ] Add whole-lab extensions, overlap checks, and pre-release reopening.
- [ ] Add per-lab browser binding, admin release, and strict IP option.
- [ ] **Test:** multiple PDFs, hidden PDFs/Markdown before start, time boundaries, overlap races, token loss, IP changes, revoked sessions.

## M5 — Submission Pipeline · v0.4 · requires M1, M4

- [ ] Add durable uploads, idempotent retries, cooldown, and pending limits.
- [ ] Implement fair queue, leases, heartbeats, retries, and stale-attempt rejection.
- [ ] Connect judging, submission history, compiler feedback, and SSE refresh.
- [ ] **Test:** acceptance races, worker/storage failures, duplicate requests, delayed judging, reconnects, live-data secrecy.
- [ ] Benchmark representative submissions on target hardware.

## M6 — Marks and Rejudge · v0.5 · requires M5

- [ ] Implement best-score selection, rounding, and admin attempt ordering.
- [ ] Add soft deletion/restoration and audit reasons.
- [ ] Add single-run rejudge and atomic full-task correction batches.
- [ ] **Test:** ties, pending versus zero, restoration, concurrent arrivals/deletions, stale batches, consistent publication.

## M7 — Python Authoring · v0.6 · requires M1, M3, M5

- [ ] Define Python checker helpers and generator/reference-solution protocols.
- [ ] Add bounded background generation, reproducible seeds, and draft review.
- [ ] **Test:** protocol errors, resource exhaustion, generator failures, hidden answers, publication gating.

## M8 — Release and Exports · v0.7 · requires M6

- [ ] Add release gates, reuse warnings, failed-case detail, and output previews.
- [ ] Add configured scoreboards and CSV/XLSX mark sheets.
- [ ] Add versioned lab archives and separate permanent-deletion action.
- [ ] **Test:** unresolved-job blocking, release/reopen rules, ownership, truncation, formula safety, archive completeness.

## M9 — Deployment Acceptance · v1.0 · requires M7, M8

- [ ] Document Compose installation, certificates, permissions, volumes, and operations.
- [ ] Test offline operation, service restarts, disk failure, and audit coverage.
- [ ] Verify 150-user API p95 <300 ms and light-load judging <30 s.
- [ ] Verify representative 150-upload burst completes within 5 minutes of first acceptance; record timeout-heavy results separately.
