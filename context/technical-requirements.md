# Technical Requirements

Implements [product-requirements.md](product-requirements.md); [design.md](design.md) describes component and UI organization. M0–M7 are implemented; later module requirements remain planned.

## Stack and Storage

- FastAPI, SQLAlchemy 2, Alembic, PostgreSQL; React/TypeScript/Vite, Tailwind, React Router; nginx with HTTPS and local assets.
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

- Enforce active-lab exclusion, acceptance time, cooldown, pending limits, deletion/restoration, and release gates under concurrency.
- Use authenticated API contracts for accounts, tasks, labs, submissions, results, operations, and exports. Define schemas, stable error codes, and upload retry/idempotency before implementation.
- Snapshot `client_ip` and nullable `client_mac` with MAC source/observation time on durable submission acceptance; preserve the original values on retries and rejudges. Reuse trusted-proxy IP handling. Browsers cannot expose client MAC addresses; use a trusted LAN lookup/integration, never student-supplied values. MAC lookup depends on network topology and may be unavailable across routers, NAT, or Docker networking. Do not block acceptance on lookup failure; select the trusted source before implementing MAC capture.
- Keep submission network metadata admin-only and retain it in lab archives. Compare IPs and available MACs across each student's lab submissions; missing MACs are not changes. DHCP, multiple interfaces, and MAC randomization mean differences suggest a PC switch rather than establish one.
- Separate student/admin response models; never send hidden data for browser-side filtering. Authorize PDFs, downloads, and SSE as well as ordinary API calls.
- Admin submission detail reads are scoped by lab and submission UUID, with no-store responses and escaped source/diagnostics. M8 must authorize student detail/source reads by ownership, binding, release, and current reveal state; no source or case detail is sent to students before release. Add failed-case input/expected output and judge/rejudge history with their planned modules.
- Lab SSE carries invalidations via one PostgreSQL LISTEN connection per API process. Reconnect with an authoritative snapshot; coalesce notifications, revalidate revoked sessions, and send keepalives without database polling.
- Anchor countdowns to server time and monotonic elapsed client time. Refresh on phase boundaries and tab visibility; no recurring health probes.
- Use PostgreSQL range exclusion for nonoverlapping schedules, lab row locks/version checks for setup, and enrollment locks for binding and freeze policy. Submission admission in M5 must reuse these locks and policy.
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
- Require admin CSRF, reasons, and audit records for deletion/restoration, retries, rejudges, and corrections. Deletion hides student records and excludes marks without removing evidence. Network flags include retained deleted evidence; missing MACs do not count as changes.
- Prioritize initial jobs over rejudges. Rejudge jobs do not consume upload slots. Fence superseded attempts, retain prior official runs during faults, and use each selected run's revision for case inputs.
- Serialize correction/review changes under the lab lock. Permit one active correction per lab task, including running and released labs; released labs stay closed. New uploads use the target revision while old official results remain visible.
- Publish staged results atomically when every active snapshot member resolves. Include completed concurrent uploads in the switch; unfinished uploads remain pending. Deletion removes a member from the gate; restoration requires current-target work. Retry infrastructure failures instead of inventing zeros. Worker startup recovers publication interrupted after the final result commit.
- Admin endpoints provide marks, best/latest attempt order, review mutations, rejudge/history, and correction progress. Student disclosure gates remain M8; trusted MAC capture remains unimplemented.

## M7 Authoring

- Python checker source belongs to draft configuration and immutable revisions; UTF-8 sources are at most 64 KiB. Helpers return bytes. `accept()`/`reject()` terminate with AC/WA; absent/malformed verdicts, exceptions, and resource failures are infrastructure faults. Compare full permitted student stdout.
- Python/C generators produce one input per consecutive seed via `argv[1]`. Python standard `random` is seeded automatically; C authors seed explicitly. Reference C stdout becomes the answer. Compile C sources once per job and cache protected executables.
- Defaults: seed 0, 1–100 cases, signed 64-bit nonnegative seeds. Each source ≤64 KiB; each input/answer ≤1 MiB, combined ≤16 MiB. Generator/reference profile: CPU 10s, wall 30s, memory 256 MiB, one process; checker CPU 5s, wall 15s, stdout 64 KiB.
- Persist job configuration, source hashes, seeds, case hashes, progress, attempts, leases, and diagnostics. `authoring_files` is writable only by API/worker and absent from student sandbox mounts; API UID 10001 owns protected directories/files. Back up this volume with PostgreSQL.
- Share existing sandboxes: initial submissions, then rejudges/corrections, then generation. Checkpoint/yield after each case; recover expired leases and fence stale attempts/generations. Three infrastructure faults exhaust automatic retries; confirmed teacher errors fail immediately.
- Permit one unresolved generation job per task. Stage results separately, preview inputs/answers, and require explicit apply confirmation. Apply replaces draft cases only for a complete job and unchanged captured draft version. Publication remains separate; existing reviewed cases can publish during pending generation. Retain applied/discarded job evidence.
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
- Worker crashes recover; stale workers cannot overwrite results. Rejudge publication never mixes revisions, including concurrent arrivals/deletions, and unresolved work blocks release.
- UI and mark sheets agree; archives include deleted evidence and export never deletes a lab.
- Multiple lab PDFs display/download correctly; missing task Markdown is valid. Test Markdown HTML/script-link rejection, pre-start access denial, and both statement formats in archives.
- Core flows work offline, including SSE reconnection. Benchmark the product targets with documented hardware, worker count, endpoint mix, fixtures, and separate timeout-heavy results.

## Remaining Decisions

M3 specifies exact byte comparison with optional one final LF/CRLF removal. Token comparison splits ASCII whitespace, with optional ASCII case folding and finite-decimal absolute/relative tolerances; NaN/Infinity receive literal comparison only. M5 defines upload idempotency, SSE invalidations, lease timing, and bounded compiler/case previews. M7 defines byte checker helpers, seeded generation, protected provenance, and shared-pool scheduling below. Remaining contracts: trusted MAC integration and archive schema/checksums. M2 defines eight-hour revocable sessions, global credentials, and CSV import behavior.

Before deployment, confirm CPU/RAM/disk/OS, representative benchmark fixtures, LAN DHCP/NAT/proxy behavior, HTTPS trust distribution, clock/storage monitoring, retention capacity, and who preserves downloaded archives.

Engineering defaults, rather than separately selected product options, include half-up rounding, three retry attempts, stale-attempt fencing, immutable revision publication, explicit schedule-conflict rejection, active-only sheet statistics, and measuring burst completion from first acceptance. Change grading, access, disclosure, or scope only through an explicit product decision.
