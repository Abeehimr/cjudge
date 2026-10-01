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

## M5a — Structured Pages · requires M5

- [x] Add browser URLs, role navigation, login return paths, and query-based pagination/filters.
- [x] Separate task library lists, drafts, and published revision views.
- [x] Separate admin lab overview, enrollment/student details, assignments/task details, and lab submissions.
- [x] Separate student lab overview, task reading/upload/history, and own lab submissions.
- [x] Preserve binding access, live updates, upload retries, and unsaved-work warnings.
- [x] **Test:** deep links, Back/Forward, filters, revocation, binding loss, dirty forms, retry keys, existing integration gates, Docker build, and HTTPS nested URLs.

## M6 — Marks and Rejudge · v0.5 · requires M5

- [x] Add admin submission URLs with inline source, current result, compiler feedback, network metadata, and retained case outputs before release.

- [x] Implement best-score selection, rounding, and admin attempt ordering.
- [x] Show submission IP/MAC and flag address changes across a student's lab attempts; test unavailable MACs and admin-only access.
- [x] Add soft deletion/restoration and audit reasons.
- [x] Add single-run rejudge and atomic full-task correction batches.
- [x] **Test:** ties, pending versus zero, restoration, concurrent arrivals/deletions, stale batches, consistent publication.

## M7 — Python Authoring · v0.6 · requires M1, M3, M5

- [x] Define byte-based Python checker helpers and seeded Python/C generator/reference protocols.
- [x] Add durable generation jobs, case checkpoints, shared-pool priority, staged review/apply, and provenance.
- [x] **Test:** protocol errors/limits, reproducible seeds, generator/reference failures, hidden artifacts, stale drafts, and worker kill/recovery.

## M8 — Release and Exports · v0.7 · requires M6

- [x] Add audited Stop now; preserve accepted work and pre-release reopening.
- [x] Add release/reveal gates, reuse warnings, own-submission detail/source, retained runs and bounded failed-case previews.
- [x] Add formula-safe final CSV mark sheets; XLSX omitted and scoreboards deferred.
- [x] Add explicit read-only archiving, verified versioned lab ZIPs and separate guarded permanent deletion.
- [x] **Test:** stop/version races, unresolved work, release/reopen rules, ownership/binding/revocation, truncation, CSV safety, archive completeness/hashes, deletion and cleanup recovery.

## M9 — Deployment Acceptance · v1.0 · requires M7, M8

- [x] Document Compose installation, certificates, permissions, volumes, and operations.
- [x] Test isolated offline services, restarts, disk failure, and audit coverage.
- [x] Verify 150-user API p95 <300 ms and light-load judging <30 s.
- [x] Verify representative 150-upload burst completes within 5 minutes of first acceptance; record timeout-heavy results separately.
- [ ] **Manual release gate:** test another LAN device with WAN disconnected: certificate trust, login/entry, PDFs, upload, and live announcements.

Evidence: [acceptance-results.json](acceptance-results.json).

## M10 — Lab Scoreboard · deferred · requires M6, M8

- [ ] **Backend:** visibility migration (default off), shared official-score/time ranking, admin/participant reads, version-checked visibility update.
- [ ] **Frontend:** dedicated lab scoreboard routes, shared table, participant visibility toggle, muted task boxes, legend, horizontal scrolling.
- [ ] **Live updates:** reuse SSE and manual refresh; invalidate visible lab standings on judging/review changes; no polling.
- [ ] **Documentation:** update architecture and admin-guide screenshot checklist.
- [ ] **Test:** score/time ties, zero-score time exclusion, earliest counted attempts, frozen students, deletion/restoration, first-solve reassignment, pending/delayed work, atomic corrections.
- [ ] **Test:** default-hidden access, enrollment/binding checks, toggle revocation, own-only links, pre-release detail protection, archived read-only state, deep links, refresh, live updates, empty roster and all colors.
- [ ] **Gate:** backend/frontend checks and database gate; concise commits per unit; stop for review.

Rules: [product-requirements.md](product-requirements.md#m10-lab-scoreboard-deferred). Interfaces: [technical-requirements.md](technical-requirements.md#m10-lab-scoreboard-deferred).
