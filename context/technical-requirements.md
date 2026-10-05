# Technical Requirements

Implements [product-requirements.md](product-requirements.md); [design.md](design.md) describes component and UI organization. M11–M16 are planned, not implemented. M0–M10 automated checks pass; physical LAN/offline browser acceptance remains. See [acceptance-results.json](acceptance-results.json).

## Stack and Storage

- FastAPI runs four Uvicorn processes; each SQLAlchemy pool allows five retained and five overflow connections. Alembic/PostgreSQL; React/TypeScript/Vite, Tailwind, React Router; nginx with HTTPS and local assets.
- Docker Compose services: `web`, `api`, `db`, runtime `worker` (process pool + isolate/cgroup v2), and standalone `judge` gate. PostgreSQL queue with `FOR UPDATE SKIP LOCKED`; no Redis requirement.
- Publish only web ports; keep API, database, and judge communication internal. Persist database/artifacts in volumes with service-specific access. Do not mount the Docker socket into application services.
- Validate the judge container's cgroup delegation, capabilities, and mounts on target Linux before implementation depends on it. Keep required elevated permissions confined to `judge`; never silently enable privileged mode across services. Upstream cautions that containerized isolate may need privileged execution: [isolate installation notes](https://github.com/ioi/isolate/blob/master/isolate.1.txt). Docker service separation does not replace the inner execution sandbox.
- The scaffold requires Python 3.14+. Verify dependency compatibility before pinning versions.
- Store metadata in PostgreSQL and artifacts at protected, application-generated paths. Use migrations, timezone-aware timestamps, and decimal/rational-safe score calculations.
- Associate PDF attachments with labs; store optional task statements as Markdown text. Authorize both by enrollment and lab start time, and include both in lab archives.
- Preserve immutable sources, revisions, and judge history. Publish accepted submission/job records only when source durability is assured; reconcile orphaned staged files after failures.

## Navigation

- Use browser routes and nginx's SPA fallback; keep API/download routes separate. Restore authenticated local destinations after login and enforce role checks on both frontend and API.
- Persist lab/task selection in paths; put pagination, submission filters, roster search, and published revision selection in query parameters.
- Filter submission histories by revision (and admin account) before pagination. Student histories remain restricted to the authenticated account and authorized browser binding.
- Retain one student SSE subscription across a lab's pages. Abort stale reads, clear private views on denied sessions, and preserve dirty form values during snapshot refreshes.
- Keep upload files and retry keys in lab-session memory, with navigation/reload warnings. Never persist credentials, source files, or session tokens in browser storage.

## Transactions and Interfaces

- Enforce schedule exclusion (per student in M16), acceptance time, cooldown, pending limits, deletion/restoration, and release gates under concurrency.
- Use authenticated API contracts for accounts, tasks, labs, submissions, results, operations, and exports. Define schemas, stable error codes, and upload retry/idempotency before implementation.
- Snapshot `client_ip` and nullable `client_mac` with MAC source/observation time on durable submission acceptance; preserve the original values on retries and rejudges. Reuse trusted-proxy IP handling. Browsers cannot expose client MAC addresses; use a trusted LAN lookup/integration, never student-supplied values. MAC lookup depends on network topology and may be unavailable across routers, NAT, or Docker networking. Do not block acceptance on lookup failure; select the trusted source before implementing MAC capture.
- Keep submission network metadata admin-only and retain it in lab archives. Compare IPs and available MACs across each student's lab submissions; missing MACs are not changes. DHCP, multiple interfaces, and MAC randomization mean differences suggest a PC switch rather than establish one.
- Separate student/admin response models; never send hidden data for browser-side filtering. Authorize PDFs, downloads, and SSE as well as ordinary API calls.
- Admin submission detail reads are scoped by lab and submission UUID, with no-store responses and escaped source/diagnostics. M8 authorizes student detail/source reads by ownership, binding, release, and current reveal state; no source or case detail is sent to students before release. Failed-case input/expected output and retained runs are available under the same gates.
- Lab SSE carries invalidations via one PostgreSQL LISTEN connection per API process. Reconnect with an authoritative snapshot; coalesce notifications, revalidate revoked sessions, and send keepalives without database polling.
- Anchor countdowns to server time and monotonic elapsed client time. Refresh on phase boundaries and tab visibility; no recurring health probes.
- Until M16, use global PostgreSQL range exclusion for schedules. M16 replaces it with concurrency-safe per-student overlap enforcement. Retain lab row locks/version checks for setup and enrollment locks for binding and freeze policy. Submission admission in M5 must reuse these locks and policy.
- Limit lab PDFs to 10 active files, 20 MiB each; announcements to 4,000 characters; assignments to 100 revisions. Bindings last one year; default strict-IP mode off. Retain PDF versions in `lab_files`, with attachment/no-store/nosniff delivery.
- Preserve previous official results during rejudge; publish replacement results/marks atomically. Handle concurrent submissions, new corrections, and deletion/restoration in the batch protocol.

## Judging and Recovery

- Short transactions claim leased jobs; do not hold a database transaction during program execution. Implement live-job priority and per-student round-robin scheduling explicitly.
- Renew leases with heartbeats and unique attempt IDs. Reject stale-worker writes and make publication idempotent.
- Retry infrastructure faults up to three total attempts, then require admin intervention. Never translate checker/sandbox/toolchain failure into a student zero.
- Compile once per judge run and execute all cases unless compilation fails. Keep AC/WA/TLE/MLE/RE/OLE/CE separate from infrastructure errors.
- Use immutable checker/test revisions. Python checkers expose `read_input()`, `read_output()`, `read_answer()`, `accept()`, and `reject()` and return binary case outcomes.
- Run generation asynchronously with bounded resources and persist reviewed cases; do not regenerate during judging.
- Size configurable workers using CPU and memory headroom; support at least one worker on a single-core host. Benchmark before increasing concurrency.
- M5: `CJUDGE_SANDBOX_INSTANCES=1` (1–32); `CJUDGE_JUDGE_MEMORY_LIMIT=1g`, at least 768 MiB per instance. One runtime container with distinct box IDs/UIDs; recreate API/worker after count changes. PostgreSQL allows 200 connections for the maximum pool.
- Claims serialize briefly to order students by last claim, then FIFO submissions. Leases last 60 seconds; busy heartbeats every 10 seconds; idle LISTEN/recovery timeout 30 seconds. Three automatic attempts then audited admin retry; delayed jobs retain pending slots. Attempt IDs and worker generations fence writes.
- Isolates status is admin-only: Starting/Idle/Judging/Generating/Faulted/Offline, last heartbeat/current job/completed count. Startup runs one compile/execute check; freshness expires after 90 seconds or an expired active lease. SSE delivers invalidations; no periodic sandbox/HTTP health probes.
- Upload UUID idempotency keys are scoped to student/lab. Filename, pinned revision, and SHA-256 must match on replay; original IP/time never change. Durability precedes database acceptance. Cleanup takes an exclusive artifact lock; uploads share it until commit.

## M6 Official Results and Corrections

- Keep mutable review state and official-run pointers separate from immutable accepted sources/revisions. Reuse one leased job per submission; retain all execution attempts and successful judge runs.
- Identify lab tasks by their task-library ID across revision changes. Historical task URLs remain valid aliases, but new uploads must use the current assigned revision; accepted idempotent retries retain the original revision.
- Compare scores as exact fractions. Ties use acceptance time then UUID; round half-up to two decimals and sum displayed task marks. Pending work never overwrites an earlier official score with zero.
- Require admin CSRF, reasons, and audit records for deletion/restoration, retries, rejudges, and corrections. Deletion retains the student's row and reason while excluding marks; evidence stays release-gated. Network flags include retained deleted evidence; missing MACs do not count as changes.
- Insert automatic announcements in the action transaction. A nullable recipient identifies public versus private messages; filter recipients server-side and send private SSE invalidations only to that account and admins. Do not include hidden grading details in notices.
- Prioritize initial jobs over rejudges. Rejudge jobs do not consume upload slots. Fence superseded attempts, retain prior official runs during faults, and use each selected run's revision for case inputs.
- Serialize correction/review changes under the lab lock. Permit one active correction per lab task, including running and released labs; released labs stay closed. New uploads use the target revision while old official results remain visible.
- Publish staged results atomically when every active snapshot member resolves. Include completed concurrent uploads in the switch; unfinished uploads remain pending. Deletion removes a member from the gate; restoration requires current-target work. Retry infrastructure failures instead of inventing zeros. Worker startup recovers publication interrupted after the final result commit.
- Admin endpoints provide marks, best/latest attempt order, review mutations, rejudge/history, and correction progress. Student disclosure gates are implemented in M8; trusted MAC capture remains unimplemented.

## M7 Authoring

- Python checker source belongs to draft configuration and immutable revisions; UTF-8 sources are at most 64 KiB. Helpers return bytes. `accept()`/`reject()` terminate with AC/WA; absent/malformed verdicts, exceptions, and resource failures are infrastructure faults. Compare full permitted student stdout.
- Python/C generators produce one input per consecutive seed via `argv[1]`. Python standard `random` is seeded automatically; C authors seed explicitly. Reference C stdout becomes the answer. Compile C sources once per job and cache protected executables.
- Defaults: seed 0, 1–100 cases, signed 64-bit nonnegative seeds. Each source ≤64 KiB; each input/answer ≤1 MiB, combined ≤16 MiB. Generator/reference profile: CPU 10s, wall 30s, memory 256 MiB, one process; checker CPU 5s, wall 15s, stdout 64 KiB.
- Persist job configuration, source hashes, seeds, case hashes, progress, attempts, leases, and diagnostics. `authoring_files` is writable only by API/worker and absent from student sandbox mounts; API UID 10001 owns protected directories/files. Back up this volume with PostgreSQL.
- Share existing sandboxes: initial submissions, then rejudges/corrections, then generation. Checkpoint/yield after each case; recover expired leases and fence stale attempts/generations. Three infrastructure faults exhaust automatic retries; confirmed teacher errors fail immediately.
- Permit one unresolved generation job per task. Stage results separately, preview inputs/answers, and require explicit apply confirmation. Apply appends generated cases after existing draft cases only for a complete job and unchanged captured draft version. Enforce the combined 100-case/16-MiB limits; rejected applies preserve both the draft and staged job. Publication remains separate; existing reviewed cases can publish during pending generation. Retain applied/discarded job evidence.
- Require admin role, CSRF, and audit for create/apply/retry/discard. SSE invalidations refresh progress and Isolates identifies Generating leases; no recurring probes. Require deterministic author programs; arbitrary clock/OS randomness cannot guarantee reproducibility.

## Isolation and Limits

All compilation, student execution, custom checking, and generation run in separate isolate profiles. Never fall back to unsandboxed execution. Allow compiler subprocesses but restrict student execution to one process, no network, and bounded temporary storage. Reset writable state per case. Hide answers, unrelated cases, checker code, credentials, and other submissions from student processes.

| Resource | Default |
| --- | --- |
| Source | Single `.c`, 64 KiB |
| CPU / wall time per case | 2 s / 6 s |
| Memory / stack | 256 MiB / 8 MiB |
| Student stdout cap | 10 MiB |
| Retained stdout / stderr | First 64 KiB each per case |
| Compilation | 10 s, 512 MiB; GCC `-O2`, C11, libm |

Compare full permitted stdout before retaining previews. Bound stderr, temporary storage, compiler diagnostics, checker output, and generator output independently. Use unique sandbox identities and cleanup after success, failure, timeout, or recovery.

## M8 Release and Exports

- Stop now changes the deadline under the lab lock/version check using server time; keep accepted uploads and retries intact.
- Preserve first release permanently and store current reveal separately. Active unresolved jobs/corrections block release and final exports; audited soft-deleted attempts do not block. M15 also excludes cancelled participation from release/export and correction publication gates.
- Serialize scheduled test selection and disclosure checks. Require reuse acknowledgment before revealing or applying visible post-release corrections involving scheduled tests, including retained revisions.
- Students read only their own active source/details after release with reveal enabled and valid binding. Retained grading runs are visible; infrastructure attempts/network metadata remain admin-only. Failed-case byte previews are capped at 64 KiB with truncation flags.
- CSV uses official exact marks and counted-run percentages; neutralize untrusted formula-like text. XLSX is omitted; optional live scoreboards are implemented in M10.
- Explicit archiving freezes lab/review/correction changes and fences unfinished excluded jobs. ZIP generation uses protected `export_files`, metadata snapshots and optimistic evidence revalidation; disk work runs outside DB transactions.
- Manifest `cjudge-lab` version 1 lists paths, sizes and SHA-256 hashes; `snapshot.json` encodes binary judge streams as `{base64: ...}`. Verify every entry before recording an export receipt. Exclude credentials/session/binding secrets and unrelated labs.
- Deletion requires an archived lab, current evidence/version receipt, valid ZIP hash, saved-copy acknowledgment, matching title and audit reason. A transaction-local lab identifier narrowly enables the immutable-submission trigger exception; ordinary updates/deletes remain forbidden.
- Persist cleanup records before deleting lab rows; retry failed source/PDF/ZIP cleanup through the admin endpoint. Preserve shared tasks/accounts and deletion audits. Unreferenced ZIPs after uncertain commits remain protected; retention/orphan cleanup belongs to M9 operations.

## M10 Lab Scoreboard

- Store `labs.scoreboard_visible` with a false default/backfill. Reuse official-result selection and stable task-library IDs across corrections; scoreboard links use the earliest counted attempt, not the newest **Best for review** attempt.
- Provide `GET /api/admin/labs/{lab_id}/scoreboard` and `GET /api/labs/{lab_id}/scoreboard`; return ordered task metadata, ranked student rows, marks, elapsed times, cell states and provisional indicators. Reuse existing session, enrollment, binding and no-store policies; deny participant reads while visibility is off.
- Keep participant responses limited to public standings. Return counted submission IDs only for the authenticated student's cells; omit other students' submission IDs, sources, case data, network metadata and private notices server-side.
- Provide `PUT /api/admin/labs/{lab_id}/scoreboard/visibility` with `{version, visible}`, using CSRF, lab version checks and archive edit protection; persist the flag, audit, announce and invalidate snapshots in one transaction. Existing result-detail authorization remains unchanged.
- Reuse exact score comparison and summed displayed marks. Sum elapsed times at database timestamp precision before formatting; no rounding before ranking. Use consistent official-result snapshots and preserve atomic correction publication.
- Add refresh-safe `/admin/labs/:labId/scoreboard` and `/labs/:labId/scoreboard` pages with one shared table; expose student navigation only when permitted. Clear standings on denial or visibility revocation and ignore stale requests.
- Reuse lab/admin SSE subscriptions and coalesced invalidations. Publish lab-wide scoreboard invalidations on relevant acceptance, judging-state, official-result and review changes when visibility is enabled; reconnect/manual refresh fetch authoritative standings. No periodic polling or extra SSE subscription per task.
- Verify ranking, timestamps, rounded totals, first-solve colors, pending/delayed states, deletion/restoration, frozen students, corrections, visibility/authentication boundaries, own-only links, routes and live updates with backend/frontend checks and a database gate.

## Planned Interfaces and Constraints — M11–M16

- **M11:** reuse roster search and credential helpers. Add bounded, selected-ID bulk reset and CSV export; reset atomically after confirmation. Generate six-character `[a-z0-9]` student credentials with `secrets`; retain hashing, encrypted credential storage, and login throttling. Browser release, password rotation, session revocation, audit, and private announcement share one transaction. Credential responses are admin-only/no-store; CSV is formula-safe, with no persistent plaintext export.
- **M12:** add active-account state and admin delete/deactivate/reactivate actions. Enforce activity on login, authenticated reads, and SSE; revoke sessions on deactivation. Check deletion eligibility transactionally and preserve audit identity snapshots rather than erasing audit history. Backfill existing accounts active; retain uniqueness for inactive roll numbers.
- **M13:** reuse native disclosure controls and shared verdict styles. Preserve escaped text, server-side recipient filtering, and existing SSE invalidations; no new UI dependency or polling.
- **M14:** persist a default-false lab setting with version-checked admin mutation, audit, announcement, and archive guard. Filter counts in student response models using the official run’s scoring revision. Return no hidden case/source fields; pending work has no invented counts. Refresh through existing SSE.
- **M15:** add independent cancellation metadata to enrollment and reason-required admin actions. Serialize cancellation, admission, reinstatement, and result publication with existing lab/enrollment locks. Do not mass-soft-delete submissions. Reuse one eligibility rule for marks, scoreboard/first-solve, final CSV, release, and correction gates; preserve excluded evidence in archives. Cancelled work may finish but cannot delay eligible batch publication. Reinstatement reconciles completed/in-flight work against the current correction target, queues missing work, and remains provisional until current results publish; stale runs cannot become counted results. Include cancellation in archive snapshots/evidence validation and fence excluded unfinished jobs at archive.
- **M16:** migrate away from global `no_lab_overlap`. Reuse scheduling/disclosure serialization with a shared per-student `[start, end)` conflict check covering enrollment/import and all schedule mutations. Check and write in one transaction so competing requests cannot both pass. Fail conflicting imports atomically, identify the conflicting student/lab/time, and preserve binding/disclosure protections. Keep the shared worker pool and global per-student fair queue.
- All new mutations require admin authorization, CSRF, audit, and existing concurrency/version protections. Extend existing APIs/types; do not add services. Each module migrates safely from the current schema without requiring other planned modules.

## Security and Operations

- Argon2 password hashing, revocable sessions, HttpOnly binding cookies, HTTPS, CSRF protection, and login rate limits. Trust forwarded IPs only from configured proxies.
- Validate archive paths, entry types, expanded sizes, and input/answer pairing. Render user content as text; protect PDF delivery with authorization, correct content type, and `nosniff`.
- Render task Markdown with raw HTML disabled and safe link protocols; do not load remote embedded assets. Preserve escaped rendering for code and diagnostics.
- Prevent formula execution from untrusted spreadsheet cells. Never log passwords, session tokens, or sensitive test contents.
- Audit logins and admin actions, including binding/time changes, revisions, deletion/restoration, result release, and exports.
- Surface worker availability, lease/retry failures, queue delay, rejudge progress, and storage failures with job/attempt identifiers.
- Define a versioned archive manifest and integrity/completion checks. Keep export separate from deletion; automated backup/restore is out of scope.
- Verify server time and browser certificate trust before a lab. Runtime must work with internet disconnected; optional LAN time synchronization is acceptable.

## Release Checks

Use pytest, Vitest, and disposable-database module gates; no coverage threshold is set. Verify:

- Best score survives later compile errors; ties, half-up rounding, deletion/restoration, and pending-versus-zero behave correctly.
- Completed upload exactly at the deadline fails; earlier accepted work counts after the deadline. Concurrent requests cannot bypass cooldown/backlog limits.
- Reopening is impossible after first release, even if reveal is disabled. Direct URLs/SSE cannot leak statements early, tests before release, or another student's records.
- Per-lab binding, same-IP token loss, strict-mode rejection, and session revocation work.
- Compiler subprocesses succeed while student fork/network/answer access fail. CPU, wall-time, memory, output, and storage exhaustion are bounded; cases cannot contaminate each other.
- Incorrect stdout beyond the retained preview still fails checking. Malformed ZIPs and generator failures cannot publish incomplete tasks.
- Worker crashes recover; stale workers cannot overwrite results. Rejudge publication never mixes revisions, including concurrent arrivals/deletions, and unresolved counted work blocks release (M15 excludes cancelled participation).
- UI and mark sheets agree; archives include deleted evidence and export never deletes a lab.
- Multiple lab PDFs display/download correctly; missing task Markdown is valid. Test Markdown HTML/script-link rejection, pre-start access denial, and both statement formats in archives.
- Core flows work offline, including SSE reconnection. Benchmark the product targets with documented hardware, worker count, endpoint mix, fixtures, and separate timeout-heavy results.

## Remaining Decisions

M3 specifies exact byte comparison with optional one final LF/CRLF removal. Token comparison splits ASCII whitespace, with optional ASCII case folding and finite-decimal absolute/relative tolerances; NaN/Infinity receive literal comparison only. M5 defines upload idempotency, SSE invalidations, lease timing, and bounded compiler/case previews. M7 defines byte checker helpers, seeded generation, protected provenance, and shared-pool scheduling below. Remaining contracts: trusted MAC integration. M2 defines eight-hour revocable sessions, global credentials, and CSV import behavior.

Before deployment, confirm CPU/RAM/disk/OS, representative benchmark fixtures, LAN DHCP/NAT/proxy behavior, HTTPS trust distribution, clock/storage monitoring, retention capacity, and who preserves downloaded archives.

Engineering defaults, rather than separately selected product options, include half-up rounding, three retry attempts, stale-attempt fencing, immutable revision publication, explicit schedule-conflict rejection, active-only sheet statistics, and measuring burst completion from first acceptance. Change grading, access, disclosure, or scope only through an explicit product decision.
