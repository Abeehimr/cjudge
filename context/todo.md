# Implementation Checklist

Each module includes its API, UI where applicable, migrations, and tests. Complete its test gate before dependent modules. Modules sharing completed prerequisites may proceed independently.

## M0 — Compose Foundation · v0.1

- [x] Define service contracts, configuration, and database volume ownership.
- [x] Add Compose services: `web` (nginx + built frontend), `api`, and `db`.
- [x] Configure private services, persistent database volume, migrations, and local HTTPS.
- [x] Add Python/frontend test tooling and repeatable Compose test commands.
- [x] **Test:** clean startup, migrations, manual readiness checks, restart persistence, private service ports.

## M1 — Sandbox Runner · v0.2 · requires M0

- [x] Add the `judge` Compose service and image with isolate.
- [x] Prove isolate/cgroup v2 operation inside `judge` on target Linux; document required permissions/mounts.
- [x] Add separate compilation, execution, checker, and generator profiles.
- [x] Implement runner input/output contract, limits, verdict mapping, and cleanup.
- [x] **Test:** valid C, compile errors, crashes, time/memory/output limits, blocked fork/network/answer access, clean state per case.
- [x] **Gate:** no submission execution until container isolation tests pass.

## M2 — Identity · v0.2 · requires M0

- [x] Add admin/student sessions, password hashing, CSRF, and rate limits.
- [x] Add CSV import, credentials sheet, password reset, and audit records.
- [x] **Test:** role separation, session revocation, malformed/duplicate imports, protected routes.

## M3 — Task Library · v0.2 · requires M0, M2

- [x] Add tasks with optional Markdown statements, immutable revisions, ZIP/pasted cases.
- [x] Implement exact/token checker contracts and scoring configuration.
- [x] Add draft validation and publish/review screens.
- [x] **Test:** optional/safe Markdown, malformed archives, traversal/size limits, checker edge cases, revision immutability, protected files.

## M4 — Labs and Binding · v0.3 · requires M2, M3

- [x] Add scheduling, enrollment, ordered tasks, and server countdown.
- [x] Add multiple lab PDF uploads, protected downloads, and dashboard links.
- [x] Add whole-lab extensions, overlap checks, and pre-release reopening.
- [x] Add per-lab browser binding, admin release, and strict IP option.
- [x] Add audited per-student freeze/unfreeze and live announcements.
- [x] **Test:** multiple PDFs, hidden PDFs/Markdown before start, time boundaries, overlap races, token loss, IP changes, revoked sessions.

## M5 — Submission Pipeline · v0.4 · requires M1, M4

- [x] Add durable uploads, idempotent retries, cooldown, and pending limits.
- [x] Save acceptance-time IP; reserve nullable MAC/source/time for a future trusted LAN integration.
- [x] Implement fair queue, leases, heartbeats, retries, and stale-attempt rejection.
- [x] Add configurable independent sandbox workers and admin Isolates status via SSE.
- [x] Connect judging, submission history, compiler feedback, and SSE refresh.
- [x] **Test:** acceptance races, worker/storage failures, duplicate requests, delayed judging, reconnects, live-data secrecy.
- [x] Benchmark 150 integer-sum submissions with ten cases and two workers; deployment acceptance remains M9.

## M6 — Marks and Rejudge · v0.5 · requires M5

- [ ] Implement best-score selection, rounding, and admin attempt ordering.
- [ ] Show submission IP/MAC and flag address changes across a student's lab attempts; test unavailable MACs and admin-only access.
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
