# Implementation Checklist

Each module includes its API, UI where applicable, migrations, and tests. Complete its test gate before dependent modules. Modules sharing completed prerequisites may proceed independently. Start each new module on its own branch from `master`; make small tested commits and merge only on the user's command.

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

## M10 — Lab Scoreboard · requires M6, M8

- [x] **Backend:** visibility migration (default off), shared official-score/time ranking, admin/participant reads, version-checked visibility update.
- [x] **Frontend:** dedicated lab scoreboard routes, shared table, participant visibility toggle, muted task boxes, legend, horizontal scrolling.
- [x] **Live updates:** reuse SSE and manual refresh; invalidate visible lab standings on judging/review changes; no polling.
- [x] **Documentation:** update architecture and admin-guide screenshot checklist.
- [x] **Test:** score/time ties, zero-score time exclusion, earliest counted attempts, frozen students, deletion/restoration, first-solve reassignment, pending/delayed work, atomic corrections.
- [x] **Test:** default-hidden access, enrollment/binding checks, toggle revocation, own-only links, pre-release detail protection, archived read-only state, deep links, refresh, live updates, empty roster and all colors.
- [x] **Gate:** backend/frontend checks and database gate; concise commits per unit; stop for review.

Rules: [product-requirements.md](product-requirements.md#m10-lab-scoreboard). Interfaces: [technical-requirements.md](technical-requirements.md#m10-lab-scoreboard).

Evidence: 33 backend tests, 48 frontend tests, frontend build, and expanded `tests/marks_gate.py` including migration defaults, permission/binding/CSRF/version gates, real cross-participant SSE, frozen marks, and correction publication parity.

Admin-guide capture: Scoreboard navigation, participant toggle off/on, sorted totals/times, shaded task boxes with legend, and a counted-submission link.

## Planned Improvements

M11–M15 are implemented; M16 remains planned and independent. Work one module at a time; make small tested commits and stop at each gate for review. Requirements: [product](product-requirements.md#planned-improvements--m11m16), [technical](technical-requirements.md#planned-interfaces-and-constraints--m11m16).

## M11 — Roster and Credentials · requires M2, M4

- [x] Add roster search, accessible row selection, visible-row select-all, and explicit selected counts.
- [x] Add confirmed atomic bulk password reset and selected-student CSV credentials.
- [x] Generate new/reset student passwords using six random lowercase letters/digits; retain existing passwords.
- [x] Make browser release reset the global password, revoke sessions, and return the new credential.
- [x] **Test:** filtered selection, nested controls, keyboard access, atomic reset, admin-only/no-store exports, CSV safety, session revocation, and no credential logging.
- [x] **Gate:** identity/binding checks pass; stop for review.

Evidence: 33 backend tests, 51 frontend tests, frontend build, disposable-database identity and lab gates.

## M12 — Account Lifecycle · requires M2, M4, M8

- [x] Add active-account state, inactive filtering, and session/access enforcement.
- [x] Delete only accounts without enrollment/submission history; preserve audit identity snapshots.
- [x] Deactivate accounts with history; preserve marks/evidence and reserve roll numbers.
- [x] Reactivate with a new password; imports cannot silently reactivate accounts.
- [x] **Test:** eligibility races, audit retention, login/SSE revocation, reactivation, import conflicts, and unchanged marks/history.
- [x] **Gate:** account lifecycle and retained-history checks pass; stop for review.

Evidence: 33 backend tests, 53 frontend tests and build, disposable-database lab and marks gates. The legacy identity gate targets the running database and was not used for M12 acceptance.

## M13 — Interface Readability · requires M4, M8

- [x] Show the latest announcement; collapse older messages with native controls.
- [x] Shade frozen roster rows muted yellow; preserve status text and task-box colors.
- [x] Shade admin/released-student testcase verdicts: AC green, WA/RE red, resource limits yellow.
- [x] **Test:** announcement order/privacy/live updates, keyboard use, verdict colors, and release-gated evidence.
- [x] **Gate:** frontend checks/build and disclosure checks pass; stop for review.

Evidence: 55 frontend tests, frontend build, disposable-database release gate.

## M14 — Optional Early Feedback · requires M4, M6, M8

- [x] Add a default-off per-lab passed/total toggle with version checks, audit, announcement, and archive protection.
- [x] Expose official counts server-side only for partial-scoring tasks when enabled.
- [x] Render pending/provisional states; keep source, cases, and streams release/reveal-gated.
- [x] **Test:** defaults, toggle authorization, scoring revisions, pending/rejudge states, SSE refresh, and hidden-data protection.
- [x] **Gate:** backend/frontend and database disclosure checks pass; stop for review.

Evidence: 33 backend tests, 57 frontend tests and build, disposable-database release gate.

## M15 — Reversible Lab Cancellation · requires M4, M6, M8, M10

- [x] Add audited cancellation/reinstatement until archive, with private reasons/announcements and read-only student access.
- [x] Exclude cancellation from marks/ranks/first-solve; add muted red unranked scoreboard rows and status in CSV/archive evidence.
- [x] Preserve accepted judging but exclude cancelled-only unfinished work from release/correction gates.
- [x] Reconcile current-revision judging on reinstatement; retain provisional state until resolved.
- [x] Preserve enrollment reservation and independent account/freeze/deletion states; never grant time or reopen released labs.
- [x] **Test:** admission/publication races, delayed cancelled work, reinstatement after corrections/release, first-solve recalculation, private reasons, exports, and archive restrictions.
- [x] **Gate:** grading/release/scoreboard database checks pass; stop for review.

Evidence: 34 backend tests, 60 frontend tests and build, disposable-database marks and release gates.

## M16 — Concurrent Labs · requires M4, M5, M8

- [x] Replace global schedule exclusion with transaction-safe unreleased enrollment reservations; reject duplicate reservations during migration.
- [x] Enforce manual/selected conflicts, partial CSV imports, late enrollment until first release, and pre-start removal. Return an emptied Scheduled lab to Draft.
- [x] Warn and require acknowledgment for reused tests in Scheduled or Running labs.
- [ ] Reuse the shared sandbox pool/fair queue; retain the 150-total-user benchmark baseline without a lab-count cap.
- [ ] **Test:** competing enrollments, partial CSV, Draft/Ended/frozen/cancelled reservations, first release and rehidden results, schedule cancellation, cross-lab access/disclosure, and worker fairness.
- [ ] **Gate:** disposable database and frontend checks plus a concurrent-lab run at 150 total users pass; record measured performance and stop for review.

Integration when applicable: verify deactivation plus cancellation, credential resets across concurrent labs, and early-feedback/release boundaries together. Preserve the outstanding M9 physical LAN/offline gate; higher capacity remains unverified.

## Improvements v2 — M17–M27

M17–M26 are complete; M19 code is complete pending physical network checks. M27 remains planned. Agreed decisions: [improvements_v2.md](improvements_v2.md). Preserve pending M16 and the outstanding M9 physical LAN/offline gate. Include migrations/API/UI/docs where needed; make small tested commits and stop at each module gate. Modules with completed prerequisites may proceed independently.

## M17 — Architecture Documentation · independent

- [x] Add `docs/schema.md`: every table, primary/foreign keys, relationships; minimal Mermaid diagram.
- [x] Add `docs/docker.md`: services, worker pool, volumes, networks, isolation, startup/shutdown.
- [x] Add `docs/network.md`: localhost/LAN, TLS/proxy, API/SSE, private services, workers.
- [x] Link from README/design; separate current architecture from planned changes; avoid duplicate diagrams.
- [x] **Gate:** diagrams match current schema/Compose; commands and links verified.

## M18 — Archive Access and Roster Removal · requires M4, M8

- [x] Hide archived labs and block student direct URLs/APIs/files/details/scoreboard/events; retain admin access.
- [x] Add individual/selected/CSV enrollment removal before start only; preserve global accounts.
- [x] Validate CSV roll numbers, preview selection, confirm atomic removal; preserve scheduled-lab last-student protection.
- [x] **Gate:** archived disclosure, live-access revocation, removal/start races, invalid/duplicate/unknown rolls, last-student protection.

Evidence: 35 backend tests, 64 frontend tests and production build; disposable-database lab/release gates cover atomic removal, CSV validation, start/removal races, archive denial and live access revocation. No migration required.

## M19 — Localhost and Multiple Network Addresses · independent

- [x] Support localhost without connectivity and simultaneous Wi-Fi/Ethernet through explicit configured hosts/interfaces.
- [x] Use relative links; validate write origins against allowed HTTPS request addresses; preserve CSRF/secure cookies.
- [x] Update certificates, configuration examples, redirects, trusted-proxy and network documentation.
- [x] **Gate:** localhost offline, both LAN interfaces, deep links/downloads/uploads/SSE, strict-IP behavior, hostile host/origin rejection.

Evidence: 36 backend tests and 64 frontend tests pass; Docker web/API builds and disposable-database lab gate pass. Temporary nginx accepts localhost and a second configured host, redirects deep links and rejects unknown hosts; API origin and port cases pass unit checks. Physical two-interface/offline browser testing remains pending.

## M20 — Lab-Owned Marks · requires M6, M8, M10

- [x] Move automatic maxima to lab-task assignments; retain task scoring rules; require marks on assignment.
- [x] Backfill assignments; preserve historical runs/configuration, archived results, verified export receipts.
- [x] Calculate current official marks from retained outcomes and assignment maxima without executing code again.
- [x] Update assignment forms, submission displays, best-attempt selection, totals, scoreboard, CSV, archives.
- [x] Allow maximum changes until archive with reason/audit/announcement.
- [x] **Gate:** task reuse with different maxima, exact scoring/rounding/ties, corrections, historical evidence, archive protection.

## M21 — Whole-Task ZIP Transfer · requires M3, M7

- [x] Define v1 task ZIP; export one published revision with statement, settings, checker, restrictions, and cases.
- [x] Import into a new draft; preserve existing tasks and exclude lab/student data and generator/reference scripts.
- [x] Add import/export controls and exact ZIP instructions to the task-authoring skill.
- [x] **Gate:** round-trip fidelity, missing assets, unsupported format, duplicates, traversal, entry types, size limits, isolated generation.

Evidence: bundle tests, disposable task API/database gate, isolated script run, frontend tests/build, skill validation. Live browser acceptance remains.

## M22 — Admin Task Tester · requires M1, M3, M5

- [x] Add separate published-revision test jobs/history through existing sandbox workers; no lab/student records or cooldown.
- [x] Accept single source or ZIP: at most 20 sources, 16 MiB compressed, existing source limits; bound expansion/outstanding jobs.
- [x] Show source, diagnostics, verdicts, case streams, pass counts/percentages; retain until explicit admin deletion.
- [x] **Gate:** bounded admission, sandbox isolation, worker recovery/fairness, hidden-data authorization, cleanup, no grading/export effects.

Evidence: 40 backend tests, 66 frontend tests and production build; disposable-database API/queue gate with real isolate passes admission, CSRF, idempotency, fairness, lease recovery, retries, case evidence, cleanup and zero student submission/run records.

## M23 — TA Accounts and Lab Operations · requires M2, M4, M15

- [x] Add TA accounts, role-detected unified login, versioned admin lab assignments, and scoped server checks.
- [x] Add TA lab/student lookup with per-task automatic marks, pre-release submissions, and standalone submission details; keep accepted-case streams hidden.
- [x] Add freeze/cancellation/browser release until archive; only acting TA/admin reverses penalties; show actor.
- [x] Add one-click audited selected-student password reveal with CSRF, no-store, and no browser persistence.
- [x] Add admin lab/TA page with assignment status, current penalties, and lab activity.
- [x] Show question names in TA submission lists and details plus inline action denials; keep TA assignments on their tab and use shaded admin TA tables.
- [x] **Gate:** disposable-database API checks for role/scope, ownership, disclosure, password/session revocation, archive locks; backend/frontend tests and build.

Evidence: 43 backend tests (including disposable PostgreSQL gate), 73 frontend tests, production build. Physical mobile/LAN acceptance remains.

## M24 — TA Review Marks · requires M20, M23

- [x] Add separate TA maximum per lab task, default disabled; admin configuration until archive.
- [x] After release, claim student, review scaled automatic suggestions, save filled marks together, and finalize when all TA-enabled tasks are saved.
- [x] Reject competing claims/stale saves; show reviewer; owner releases unfinished claims/admin transfers with audit.
- [x] Permit original TA/admin reopening; other TAs cannot overwrite finalized reviews.
- [x] Show admin remaining reviews, automatic/TA/combined totals; admin exports include separate/combined marks.
- [x] Keep TA marks hidden from students and scoreboard; exclude cancelled participation, retain review evidence.
- [x] Scale marks from stored fractions on maximum changes; zero maximum only when no reviews exist.
- [x] Retain reviews on grading changes, flag Needs recheck; archive permits incomplete reviews and locks changes.
- [x] Show TA maxima in lab task table; set both maxima when adding tasks; make assigned TA rows clickable.
- [x] **Gate:** claim/save/finalize races, zero/no-submission marks, scale/rounding, reopen/transfer, cancellation/freeze, disclosure, exports/archive.

Evidence: backend/frontend tests and build, disposable PostgreSQL service/API gates. Physical mobile/LAN acceptance remains.

## M25 — Restricted Source Identifiers · requires M3, M5

- [x] Add optional revisioned case-sensitive banned identifiers; empty lists skip scanning.
- [x] Retain rejection as Restricted source, matched identifier/line, zero automatic marks; do not compile/run.
- [x] Apply to student judging/rejudging and tester; show rules and reasons; document bypass limits.
- [x] **Gate:** token boundaries, escapes/comments/literals/malformed source, correction/history, no execution after rejection.

Evidence: scanner unit tests, disposable PostgreSQL worker/tester/API/archival gate, existing tester/release/TA gates, frontend tests and build. Live lab acceptance remains.

## M26 — C++17 Support · requires M1, M3, M5

- [x] Add revision-level C11/C++17/both allowlist; existing tasks default C11; persist extension-derived source language.
- [x] Add isolated g++ C++17 compilation and independent generator/reference language selection.
- [x] Extend uploads, details/downloads, rejudge, tester, restrictions, task ZIP v2 and lab archive v5.
- [x] Block correction narrowing for every incompatible retained submission, including deleted/cancelled evidence.
- [x] **Gate:** migration/receipt compatibility, admission/retries, mixed tester batches, compiler errors/timeouts/recovery, authoring and frontend checks.

Evidence: disposable PostgreSQL/API tests, real worker startup/student judging, real isolate C++17/STL and C++/Python authoring gates, real tester queue/recovery gate, existing marks/release gates, backend/frontend tests and Docker builds. Live browser acceptance remains.

## M27 — Focused UI Improvements · requires M4, M5, M15

- [ ] Add independent frozen/cancelled filters to admin roster only; preserve search/URL state.
- [ ] Add student top-bar quick-submit dialog with task/file selection; reuse upload/idempotency/error handling.
- [ ] a proper big timer or a loading bar for remaining time
- [ ] adding a task should ask for task only then revision separatly.
- [ ] when a row has a checkbox the whole row should be clickable to select/deselect the checkbox.
- [ ] the error messages should be at top or almost at top of page (for example Student reserved by unreleased was shown in the bottom)
- [ ] **Gate:** mobile/keyboard use, cooldown, binding loss, freeze/cancellation, deadline, safe retries.

Integration when applicable: test TA reviews with maximum changes, cancellations, corrections and archives; test tester/ZIP/source restrictions with C++. Refresh M17 diagrams as modules land. Higher capacity remains unverified.
