# PF Lab Auto-Judge: Requirements v1

A DOMjudge-inspired auto-checker for Programming Fundamentals (C) labs. Runs on one Linux server, LAN-only, one lab at a time, 100+ concurrent students.

## 1. Scope

**In v1:** C only, single `.c` file per submission, stdin/stdout only, one admin, one active lab at a time, PDF task statements, fully offline operation.

**Not in v1:** other languages (design stays language-pluggable), multiple admins/TAs, concurrent labs, in-browser editor, TC subtask groups, plagiarism detection (deferred to v2, see section 8), internet access.

## 2. Roles

| Role | Can do |
| --- | --- |
| Admin (single) | Everything: tasks, TCs, labs, accounts, time control, rejudge, mark sheets, plagiarism, archive |
| Student | Log in, read statements once the lab starts, submit, see pass/fail, see detailed results only if released |

## 3. Tasks (admin)

- Fields: title, PDF statement, max marks, checker type, limits (override of defaults), marking mode.
- **Marking mode (per task):** *partial* (marks × passed/total), *all-or-nothing*, or *weighted TCs* (points per TC).
- **Adding test cases (all supported):**
  1. Zip upload of `N.in` / `N.out` pairs.
  2. Paste TCs in the web UI.
  3. Generator script + reference C solution. The system runs both in the sandbox at save time and stores the resulting `.in`/`.out` files for review.
- **Checker types (per task):**
  - **Exact match:** byte-for-byte comparison (optional: ignore a single trailing newline).
  - **Token-based:** whitespace-insensitive token comparison, with optional case-insensitive mode and optional float tolerance (absolute/relative epsilon).
  - **Custom checker:** Python script using our helper library (`read_input()`, `read_output()`, `read_answer()`, `accept()`, `reject()`), or a C++ testlib checker. Both run in the sandbox with their own limits.

## 4. Labs (admin)

- Fields: name, start time, duration, assigned students, ordered tasks, settings below.
- Only **one lab can be active at a time** (the system blocks overlapping labs).
- Statements are **hidden until the lab starts**.
- **Lifecycle:** Draft → Scheduled → Running → Ended → Results released → Archived.
- **Per-lab settings:**

| Setting | Options | Default |
| --- | --- | --- |
| Counting policy | best within lab time / last / first fully-passing | best within lab time |
| Submission cooldown | seconds | 30 |
| Compile-error visibility | full / first \~20 lines / just "Compile Error" | first \~20 lines |
| Scoreboard | none / admin-only / visible to students | admin-only |
| Post-lab reveal | on / off (toggle any time after the lab ends) | off |

- **Time control:** extend the whole lab, or extend individual students.
- **Deadline rule:** a submission is timestamped when the server receives it. If that is before the (possibly extended) deadline, it is judged and counted even if judging finishes later.

## 5. Accounts and identity

- Admin bulk-imports a CSV (roll no, name). Passwords are auto-generated, with a printable credentials sheet and a per-student password reset.
- **Hybrid login binding:**
  1. Student logs in with roll no + password.
  2. First login binds the account to a device token (httpOnly cookie) and the client IP.
  3. Same device token: login allowed. If the IP changed (e.g. DHCP), it is allowed but logged and flagged.
  4. No token, different IP: **blocked** until the admin clicks **Release** in the dashboard.
  5. Optional strict mode (per lab): IP must also match.
- Every login attempt and submission stores the IP for audit.
- Pre-lab check in the dashboard shows the IPs seen, to catch NAT (many students sharing one IP).
- Admin login is separate, with a strong password and an optional IP allowlist.

## 6. Student experience

- Dashboard: lab countdown (server-authoritative), task list, PDF statement, upload `.c`, submission history.
- Status per submission: Queued → Judging → **Passed** / **Failed** (plus Compile Error per the lab setting). Live updates via SSE.
- Students only ever see pass/fail during the lab. Internally the system stores the exact verdict (AC/WA/TLE/MLE/RE/OLE/CE) for the admin.
- After the admin releases results: overall % of TCs passed, per-TC pass/fail, and **input + expected output for failed TCs**.
- Students can only see their own data.

## 7. Marks

- Per task: marks from the counted submission (highest marks; ties go to the earliest).
- **Mark sheet (CSV and XLSX), downloadable from the admin dashboard:** roll no, name, per-task marks, per-task % of TCs passed, total marks, submission count, last submission time.
- **Rejudge:** all submissions of a task (after fixing a TC), and single submission. Marks are recomputed and the action is audit-logged.

## 8. Plagiarism detection (deferred to v2)

Not part of v1. Every submission's source is stored and retained in archives, so it can be added later without data loss. The planned v2 design is a self-hosted JPlag or Dolos run as a low-priority background job on each task's counted submissions, with a flagged-pairs dashboard (similarity %, side-by-side view, confirm/dismiss) and a plagiarism flag column in the mark sheet.

## 9. Sandbox and judging

- **Sandbox: isolate** (cgroup v2, namespaces, read-only root, no network). Compile, run, checker and generator all execute inside it.
- **Workers:** admin sets the number of sandboxes. Default is cores − 1, with a warning if set above the core count. Workers are pinned to dedicated cores.
- **Pipeline:** upload → validate (`.c`, ≤ 64 KB) → store → queue → compile → run all TCs → check → record.

| Limit | Default (overridable per task) |
| --- | --- |
| CPU time per TC | 2 s (wall-clock backstop 3× = 6 s) |
| Memory | 256 MB |
| Stack | 8 MB |
| Processes | 1 (no fork) |
| Output size | 10 MB |
| File writes / network | none (small tmpfs only) / none |
| Compile | 10 s, 512 MB, `gcc -O2 -std=c11 -lm` |

- **Queue:** fair per-student round-robin. Priority: live submissions > rejudge.
- All TCs run for every submission (needed for the % on reveal). Skipped only on compile error.
- Crash safety: jobs are leased and re-queued if a worker dies.
- **Capacity note:** worst case is 100 students × TCs × 2 s CPU. Plan workers so a deadline burst clears in a few minutes. The load test in M5 will verify this on your hardware.

## 10. Architecture

- **Backend:** FastAPI, SQLAlchemy 2 + Alembic, PostgreSQL. Job queue in PostgreSQL (`FOR UPDATE SKIP LOCKED`), so no Redis is needed.
- **Judge workers:** separate processes managed by systemd on the host (isolate needs host cgroups).
- **Frontend:** React + TypeScript + Vite, Tailwind, TanStack Query, all assets bundled locally (no CDN, offline-safe).
- **Serving:** nginx in front (static frontend, API proxy, PDF serving with `application/pdf` + `nosniff`), self-signed HTTPS recommended.
- **Storage:** metadata in PostgreSQL, files on disk. Nightly backup of DB and files to an admin-defined path.
- **Targets:** 150 concurrent users, a burst of 150 submissions within 60 s, API p95 \< 300 ms. The web tier is light, and judging is the bottleneck.
- Server clock via NTP is the single source of truth for all deadlines.

## 11. Security

- Argon2 password hashing, CSRF protection, login rate limiting.
- Hidden TC data is never exposed before release, and only failed-TC data after release.
- Upload validation and strict content types. Checkers and generators are sandboxed.
- Audit log covers admin actions, logins, releases, rejudges and time extensions.

## 12. Data retention

Admin can **archive a lab as a zip** (submissions, marks, logs, TCs, statements, mark sheets), then delete it from the system.

## 13. Decisions I made (veto any of these)

PostgreSQL as queue (no Redis) · React + TS + Vite · SSE for live updates · fair per-student queue · all TCs always run · no TC groups in v1 · tie-break = earliest submission · exact match is byte-exact with optional trailing-newline ignore · default compile-error visibility "first \~20 lines" · generators are Python or C · Argon2 · 64 KB source limit.

## 14. Still to confirm

1. Server core count (sets the default worker count).
2. Typical size: tasks per lab, TCs per task, lab duration (for capacity planning).
3. Whether failed-TC reveal should also show the student's own output (I'd suggest yes, truncated).
4. Lab machine IP behaviour (unknown). Default is token-primary binding with IP-change flagging, which tolerates DHCP.

## 15. Milestones

| M | Contents |
| --- | --- |
| M1 | Auth, tasks, TC upload, isolate sandbox, judge worker, submit and see pass/fail |
| M2 | Labs, timing, extensions, marks, mark sheet, post-lab reveal |
| M3 | Token and custom checkers (Python + testlib), generator, rejudge |
| M4 | Hybrid identity binding + release, CSV import, credentials sheet, archive/export |
| M5 | Scoreboard, load test and hardening |
| v2 | Plagiarism detection, more languages, TAs, concurrent labs |