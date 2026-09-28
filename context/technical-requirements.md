# Technical Requirements

Implements [product-requirements.md](product-requirements.md); [design.md](design.md) describes component and UI organization. These are planned requirements, not existing services.

## Stack and Storage

- FastAPI, SQLAlchemy 2, Alembic, PostgreSQL; React/TypeScript/Vite, Tailwind, TanStack Query; nginx with HTTPS and local assets.
- Docker Compose services: `web` (nginx + built frontend), `api`, `db` (PostgreSQL), and `judge` (worker + isolate/cgroup v2). PostgreSQL queue with `FOR UPDATE SKIP LOCKED`; no Redis requirement.
- Publish only web ports; keep API, database, and judge communication internal. Persist database/artifacts in volumes with service-specific access. Do not mount the Docker socket into application services.
- Validate the judge container's cgroup delegation, capabilities, and mounts on target Linux before implementation depends on it. Keep required elevated permissions confined to `judge`; never silently enable privileged mode across services. Upstream cautions that containerized isolate may need privileged execution: [isolate installation notes](https://github.com/ioi/isolate/blob/master/isolate.1.txt). Docker service separation does not replace the inner execution sandbox.
- The scaffold requires Python 3.14+. Verify dependency compatibility before pinning versions.
- Store metadata in PostgreSQL and artifacts at protected, application-generated paths. Use migrations, timezone-aware timestamps, and decimal/rational-safe score calculations.
- Preserve immutable sources, revisions, and judge history. Publish accepted submission/job records only when source durability is assured; reconcile orphaned staged files after failures.

## Transactions and Interfaces

- Enforce active-lab exclusion, acceptance time, cooldown, pending limits, deletion/restoration, and release gates under concurrency.
- Use authenticated API contracts for accounts, tasks, labs, submissions, results, operations, and exports. Define schemas, stable error codes, and upload retry/idempotency before implementation.
- Separate student/admin response models; never send hidden data for browser-side filtering. Authorize PDFs, downloads, and SSE as well as ordinary API calls.
- SSE reconnection refreshes authoritative state. Define event identity/replay explicitly.
- Preserve previous official results during rejudge; publish replacement results/marks atomically. Handle concurrent submissions, new corrections, and deletion/restoration in the batch protocol.

## Judging and Recovery

- Short transactions claim leased jobs; do not hold a database transaction during program execution. Implement live-job priority and per-student round-robin scheduling explicitly.
- Renew leases with heartbeats and unique attempt IDs. Reject stale-worker writes and make publication idempotent.
- Retry infrastructure faults up to three total attempts, then require admin intervention. Never translate checker/sandbox/toolchain failure into a student zero.
- Compile once per judge run and execute all cases unless compilation fails. Keep AC/WA/TLE/MLE/RE/OLE/CE separate from infrastructure errors.
- Use immutable checker/test revisions. Python checkers expose `read_input()`, `read_output()`, `read_answer()`, `accept()`, and `reject()` and return binary case outcomes.
- Run generation asynchronously with bounded resources and persist reviewed cases; do not regenerate during judging.
- Size configurable workers using CPU and memory headroom; support at least one worker on a single-core host. Benchmark before increasing concurrency.

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
- Prevent formula execution from untrusted spreadsheet cells. Never log passwords, session tokens, or sensitive test contents.
- Audit logins and admin actions, including binding/time changes, revisions, deletion/restoration, result release, and exports.
- Surface worker availability, lease/retry failures, queue delay, rejudge progress, and storage failures with job/attempt identifiers.
- Define a versioned archive manifest and integrity/completion checks. Keep export separate from deletion; automated backup/restore is out of scope.
- Verify server time and browser certificate trust before a lab. Runtime must work with internet disconnected; optional LAN time synchronization is acceptable.

## Release Checks

Establish test tooling as components arrive; no runner or coverage threshold exists yet. Verify:

- Best score survives later compile errors; ties, half-up rounding, deletion/restoration, and pending-versus-zero behave correctly.
- Completed upload exactly at the deadline fails; earlier accepted work counts after the deadline. Concurrent requests cannot bypass cooldown/backlog limits.
- Reopening is impossible after first release, even if reveal is disabled. Direct URLs/SSE cannot leak statements early, tests before release, or another student's records.
- Per-lab binding, same-IP token loss, strict-mode rejection, and session revocation work.
- Compiler subprocesses succeed while student fork/network/answer access fail. CPU, wall-time, memory, output, and storage exhaustion are bounded; cases cannot contaminate each other.
- Incorrect stdout beyond the retained preview still fails checking. Malformed ZIPs and generator failures cannot publish incomplete tasks.
- Worker crashes recover; stale workers cannot overwrite results. Rejudge publication never mixes revisions, including concurrent arrivals/deletions, and unresolved work blocks release.
- UI and mark sheets agree; archives include deleted evidence and export never deletes a lab.
- Core flows work offline, including SSE reconnection. Benchmark the product targets with documented hardware, worker count, endpoint mix, fixtures, and separate timeout-heavy results.

## Remaining Decisions

Before the relevant component is built, specify checker newline/encoding/case/tolerance/NaN rules; Python helper protocol; generator invocation, seeds, manifest and limits; stderr/temp/ZIP/diagnostic caps; session expiry/reset revocation and credential handling; CSV duplicate/error behavior; database/API schemas; upload idempotency; SSE replay; lease timing; generation scheduling; correction-batch transactions; and archive schema/checksums.

Before deployment, confirm CPU/RAM/disk/OS, representative benchmark fixtures, LAN DHCP/NAT/proxy behavior, HTTPS trust distribution, clock/storage monitoring, retention capacity, and who preserves downloaded archives.

Engineering defaults, rather than separately selected product options, include half-up rounding, three retry attempts, stale-attempt fencing, immutable revision publication, explicit schedule-conflict rejection, active-only sheet statistics, and measuring burst completion from first acceptance. Change grading, access, disclosure, or scope only through an explicit product decision.
