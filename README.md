# cJudge

Offline C lab judge. M0–M4 provide HTTPS, isolation, accounts, tasks, and labs. M5 adds durable C submissions, fair asynchronous judging, a configurable sandbox pool, and an admin Isolates panel. M6 adds official marks, audited deletion/restoration, rejudge history, and atomic task corrections. M7 adds sandboxed Python/C test generation and Python checkers. M8 adds Stop now, release-gated student details, CSV sheets, verified ZIP archives, and guarded permanent deletion.

## Repository layout

User guides: [Student lab guide](docs/guides/student.md) and [TA released-results guide](docs/guides/ta.md). Both include interface screenshots and placeholders for remaining captures. The admin guide is the next documentation module.

To export both guides with screenshots, install LibreOffice and run `python3 scripts/export-guides.py`. PDFs are written to `docs/guides/pdf/`. Direct Markdown-to-PDF conversion can omit linked images; this command embeds them through intermediate HTML.

- `src/cjudge/`: backend feature packages `identity/`, `tasks/`, `labs/`, `submissions/`, and `judging/`; `api.py` assembles routes and `runner.py` provides the sandbox runner.
- `src/frontend/`: React app, package configuration, and component tests.
- `deploy/`: nginx configuration and judge entrypoint/isolate configuration.
- `tests/`, `migrations/`, `scripts/`, `context/`: backend checks, schema revisions, local operations, and requirements.

Compose, Dockerfiles, and Python package configuration stay at the repository root. Account setup commands remain `python -m cjudge.identity ...`.

## Local setup

Requires Docker Compose, OpenSSL, and Node.js for local frontend checks.

1. Copy `.env.example` to `.env`. Replace `POSTGRES_PASSWORD` with a long random alphanumeric value. Set `CJUDGE_UID` and `CJUDGE_GID` to your `id -u` and `id -g` output.
2. Run `sh scripts/create-cert.sh localhost`. For a LAN name or IP, pass its certificate subject and SAN list, for example `sh scripts/create-cert.sh cjudge.lab 'DNS:localhost,IP:127.0.0.1,DNS:cjudge.lab'`.
3. Run `docker compose build api key-init web`. On a fresh installation only, run `docker compose run --rm key-init` to create the student credential key.
4. Run `docker compose up -d db`. Once `docker compose exec -T db pg_isready -U cjudge -d cjudge` reports "accepting connections", run `docker compose run --rm api alembic upgrade head`.
5. On first setup, run `docker compose run --rm api python -m cjudge.identity create-admin` and enter an admin password twice. The admin username is `admin`.
6. Run `docker compose up -d web` and `sh scripts/smoke.sh`. Open `https://localhost:8443`; trust `certs/server.crt` in lab browsers before real use. The default certificate is self-signed.

Only localhost ports 8080 and 8443 are published by default. See LAN setup below to expose nginx; keep `api` and `db` private.

Stop services with `docker compose down`. The PostgreSQL volume survives container recreation; `docker compose down --volumes` deletes it.

## LAN setup

1. Reserve the server's IPv4 address in DHCP or use a static IP. Find the current address with `ip -4 route`; use the LAN address, not a Docker bridge address. The example below uses `192.168.0.106`; replace it with your server address.
2. Set these entries in `.env`:
   ```dotenv
   CJUDGE_BIND_ADDRESS=192.168.0.106
   CJUDGE_ALLOWED_HOSTS=localhost,127.0.0.1,192.168.0.106
   CJUDGE_PUBLIC_ORIGIN=https://192.168.0.106:8443
   ```
   `CJUDGE_BIND_ADDRESS=0.0.0.0` optionally listens on all IPv4 interfaces; a specific LAN address limits exposure. Login accepts the configured public origin only: admins on the server must use the LAN URL too.
3. Generate the certificate with an IP SAN:
   ```sh
   sh scripts/create-cert.sh 192.168.0.106 'DNS:localhost,IP:127.0.0.1,IP:192.168.0.106'
   docker compose up -d --force-recreate api web
   sh scripts/smoke.sh https://192.168.0.106:8443 http://192.168.0.106:8080
   ```
   Certificate generation replaces the existing certificate/key. Keep a protected copy before replacement if you need rollback. Install only `certs/server.crt` as trusted in lab browsers/devices; never distribute `server.key`. Changed certificates require updated trust. No database migration is needed; volumes and workers remain unchanged.
4. If a host firewall is enabled, allow TCP 8080/8443 from the lab subnet. Check Docker's published-port firewall behavior; do not rely on UFW alone to restrict Docker ports. Disable Wi-Fi client isolation on the lab network if it prevents devices reaching the server. Do not add router port forwarding.
5. From another device, open `https://192.168.0.106:8443`. Check student/admin login and logout, lab entry, PDFs, uploads, live announcements, and recorded student IPs. Confirm API/database ports are not published. Repeat with internet disconnected but LAN connected.

To return to local-only access, restore `CJUDGE_BIND_ADDRESS=127.0.0.1`, localhost host/origin settings, and the prior certificate (or generate a new localhost certificate), then recreate API/web. If DHCP changes the server IP, update the configuration, certificate, and client trust before the next lab.

## Checks

- Backend: `uv sync --locked && uv run pytest -q`
- Frontend: `npm ci --prefix src/frontend && npm run test --prefix src/frontend && npm run build --prefix src/frontend`
- Compose: `docker compose config --quiet && docker compose up -d --build web && sh scripts/smoke.sh`
- Identity gate: `docker compose run --rm -v ./tests:/app/tests:ro api python tests/identity_gate.py`
- Task gate: `docker compose run --rm -v ./tests:/app/tests:ro api python tests/tasks_gate.py`
- Lab gate: `docker compose run --rm -v ./tests:/app/tests:ro api python tests/labs_gate.py`
- Submission admission gate: `docker compose run --rm -v ./tests:/app/tests:ro api python tests/submissions_gate.py`
- Marks/rejudge gate: `docker compose run --rm -v ./tests:/app/tests:ro api python tests/marks_gate.py`

Compose has no periodic health probes. Run `sh scripts/smoke.sh` when you want a readiness check.

The source of truth for product behavior and implementation modules is in `context/`.

## Pages and navigation

Admin navigation has **Labs**, **Students**, **Task Library**, and **Isolates**. Open a lab for **Overview**, **Students**, **Tasks**, and **Submissions**. Overview contains schedule/start controls, PDFs, announcements, and compiler feedback. Open a roster student for binding/IP and freeze/release controls with their submission history. Open an assigned task for its pinned revision and task submissions.

Students open a lab overview, then a task page to read and submit together. **Submissions** lists their own lab attempts. Lists show newest submissions first; filters and pagination remain in the URL. There is no global submission page.

Refresh or bookmark a nested URL, such as `/admin/labs/<lab-id>/students/<student-id>` or `/labs/<lab-id>/tasks/<revision-id>`. Login returns to the requested page; valid browser bindings resume without another **Enter lab**. Unsaved forms and selected files trigger navigation warnings. Unconfirmed uploads retain the same file/key while navigating within the lab, but files must be selected again after a reload. No new database migration is needed for this navigation update; rebuild API/web images and run `docker compose up -d web`.

## M2 accounts

Student accounts are global: each roll number keeps one password across labs. Admin can add students manually or import UTF-8 CSV with `roll_number,name` headers, up to 1 MiB/1,000 rows. Existing roll numbers keep their name/password; name mismatches are reported. Admin can edit names, reveal/print selected credentials, and reset student passwords. Students cannot change passwords. Enroll global accounts from Admin → Labs.

Admin password is hash-only. Student passwords are hashed for login and separately encrypted for admin reprints. Keep the `credential_keys` Docker volume with database backups; losing it makes existing student passwords unrecoverable. The API mounts that volume read-only. `key-init` refuses to overwrite an existing key. Never copy the key, password sheets, or `.env` into Git. To reset the admin password, run `docker compose run --rm api python -m cjudge.identity reset-admin`; existing admin sessions are revoked.

Before upgrading another installation, check for an existing student roll `ADMIN` and resolve that identifier collision.

The shared login form accepts `admin` or a student roll number; `ADMIN` is reserved and cannot be imported or created as a student. The UI uses a light theme with blue actions, yellow notices, and red errors/frozen states.

Sessions last eight hours. Logout and password resets revoke sessions. Login is rate-limited per account, while nginx allows a shared lab IP burst. Credential responses are not cached. No public registration exists.

## M3 task library

After updating an existing installation, run `docker compose build api web`, then `docker compose run --rm api alembic upgrade head` and `docker compose up -d web`. Under **Admin → Task Library**, create a draft, add pasted cases or a ZIP of flat `N.in`/`N.out` pairs, review settings/cases, and publish a revision. Task statements are optional Markdown; HTML and embedded images do not render. Case downloads remain admin-only; lab students see statements and public resource limits.

ZIPs are limited to 17 MiB compressed, 16 MiB expanded, 100 paired cases, and 1 MiB per input/answer. Exact checking compares bytes, optionally ignoring one final LF/CRLF. Token checking splits ASCII whitespace, with optional case and finite-number tolerances. `src/cjudge/tasks/grading.py` defines both comparison and rational scoring for M5. Published revisions retain their original configuration and cases. Draft edits use version checks and may return 409; reload before retrying.

The `task_files` volume contains protected case sets and must be backed up with PostgreSQL. Losing it makes published tests unavailable. Replacing draft cases can leave unreferenced files after interrupted transactions; keep the volume until archive/cleanup support arrives.

## M4 labs

Upgrade with `docker compose build api web`, `docker compose run --rm api alembic upgrade head`, then `docker compose up -d web`.

Under **Admin → Labs**, create a lab, assign ordered published revisions, enroll students, and upload lab PDFs. Schedule a future start or choose **Start now**. At least one task/student is required; PDFs may be omitted only when every task has a Markdown statement. Overlapping lab windows are rejected. Task assignments and enrollment removals close at start; late additions remain available.

Students select their assigned lab and explicitly **Enter lab** after start. This binds the browser; missing cookies require admin release even at the same IP. Release revokes all that student's sessions. Strict IP matching defaults off; otherwise IP changes are allowed and flagged. Browser binding remains required after the lab ends.

Test announcements and PDF replacement with a student tab open: SSE refreshes materials and deadlines. Previous PDFs remain admin-only. Test **Freeze/Unfreeze**, browser release, whole-lab extension, and pre-release reopening; reasons are audited. Freeze blocks new submissions while materials stay readable.

Lab time, PDF, problem/correction, and result changes automatically post announcements, including supplied reasons. Individual deletion/restoration, rejudge/retry, freeze, and binding-release notices reach only the affected student; admins see their audience. Deleted student submissions remain listed with their reason and exclusion from marks; source and judging details remain release-gated. This update adds migration `20261006_notices`: rebuild API/web/worker, stop API/worker, migrate, then restart.

Back up `lab_files` with PostgreSQL. PDFs have immutable UUID paths, up to 10 active files of 20 MiB each. Interrupted transactions may leave unreferenced files; retain the volume until cleanup support arrives. API owns this volume as UID/GID 10001; if an older image initialized it as root, run `docker compose run --rm --user root api chown 10001:10001 /var/lib/cjudge-labs` before use.

## M1 sandbox checks

Requires rootful Docker on Linux with cgroup v2 and kernel 5.19+. Docker Desktop and rootless Docker are not validated.

```sh
docker compose build judge
docker compose run --rm judge
```

The default command runs the M1 isolation gate and exits nonzero on failure. It needs no web/API/database services. The `sandbox` Compose profile keeps the runner out of ordinary M0 startup. Image builds require internet; runs use `network_mode: none`.

The gate checks C11/libm compilation, compile errors, crashes, CPU/wall/memory/output limits, storage/inode exhaustion, blocked forks/network access, hidden files/environment, Python profiles, clean cases, and cleanup after controller failure.

### Permissions and deployment

Only the standalone `judge` and runtime `worker` receive `SYS_ADMIN`, `SYS_RESOURCE`, `NET_ADMIN` (to bring up the sandbox's loopback interface), and an unconfined **outer** seccomp profile; isolate applies its own syscall restrictions inside each sandbox. Neither is privileged, publishes ports, or mounts the Docker socket. The standalone gate has no application credentials/network; the runtime worker accesses PostgreSQL through an internal network. Submitted programs receive neither database credentials nor artifact mounts. Both root filesystems are read-only, with no swap.

The entrypoint mounts the container's private cgroup v2 namespace, moves itself into `manager`, and enables CPU/memory/PID controllers. It never mounts the host cgroup tree. Inner programs use distinct UID/GIDs starting at 60000 with no capabilities. Compilation may spawn 32 processes; other profiles allow one. Run one worker container; scale its internal pool. Stop it before running standalone isolation/judging gates, which reuse the same UID range.

Use `docker compose run`, not `exec`: moving the container's main process enables controller delegation, but Docker cannot insert an exec process into the now-internal cgroup. No host configuration is changed by setup. If mounts or controller delegation fail, fix the host policy; there is no unsandboxed fallback. See [upstream isolate installation guidance](https://www.ucw.cz/isolate/isolate.1.html).

Host crash collectors are outside container limits. If `cat /proc/sys/kernel/core_pattern` starts with `|`, configure the host collector to discard sandbox core dumps before accepting real submissions. For systemd-coredump, `Storage=none` and `ProcessSizeMax=0` disable dump storage/processing host-wide; apply that policy only on the dedicated judge host. `--core=0` alone does not disable a piped host collector. See [coredump.conf(5)](https://www.man7.org/linux/man-pages/man5/coredump.conf.5.html).

### Runner contract

Worker-only functions live in `src/cjudge/runner.py`: `compile_c(source)` returns an executable on success; `execute(executable, stdin, limits)` runs one fresh case; `run_python(script, profile, files)` isolates checker/generator code. Python authoring protocols remain M7 work. Inputs are bytes and supplied filenames must be plain basenames.

`Result` includes verdict, bounded full stdout, first 64 KiB of stderr, CPU/wall seconds, and peak memory in KiB. `stdout_preview` returns the first 64 KiB. `OK` means execution succeeded; AC/WA comparison is defined in M3 and wired to judging in M5. Student failures map to CE/RE/TLE/MLE/OLE. Checker and infrastructure failures raise `SandboxError`, never a student score. MLE requires a confirmed cgroup OOM kill; allocation failure without OOM is handled by the program and may produce RE.

Defaults follow `context/technical-requirements.md`. Temporary storage is 64 MiB (128 MiB for compilation), capped at 1,024 inodes. Stderr is capped at 1 MiB; compiler stdout at 1 MiB; checker stdout at 64 KiB. Source is capped at 64 KiB, stdin at 10 MiB, and staged files at 16 MiB. Checking uses full permitted output before preview truncation. Each worker owns a locked sandbox; writable state and cgroups are removed after every run.

## M5 submissions and sandbox pool

Upgrade with `docker compose build api web worker`, then `docker compose run --rm api alembic upgrade head` and `docker compose --profile judging up -d web worker`. Database migrations must finish before starting workers. If an older image initialized the new volume as root, run `docker compose run --rm --user root api chown 10001:10001 /var/lib/cjudge-submissions` once.

Set `.env` values `CJUDGE_SANDBOX_INSTANCES=2` and `CJUDGE_JUDGE_MEMORY_LIMIT=2g` for two workers. Defaults are one worker and 1 GiB. Allow at least 768 MiB per instance and leave CPU/RAM headroom for other services; startup rejects insufficient memory. Recreate both API and worker after changing the count: `docker compose --profile judging up -d --force-recreate api worker`. Do not scale worker containers with `--scale`.

Students enter a running lab, open a task page, and upload one nonempty `.c` file up to 64 KiB. Cooldown is 30 seconds across tasks; at most three submissions may be pending. An unconfirmed upload retains its idempotency key for **Retry upload**, including after closure. Accepted records and IP remain immutable. MAC displays as unavailable until a trusted LAN integration exists.

Workers compile once and run every case independently. Students see opaque status and configured compiler feedback, not partial marks or hidden cases. Admin → Labs shows submissions, protected source downloads, and audited retries for delayed judging. Three infrastructure attempts exhaust the automatic budget; unresolved faults never become student zeros. Admin → Isolates shows configured/healthy/working counts, heartbeats, current work, and sanitized faults. Startup checks prove each sandbox works; 10-second busy and 30-second idle heartbeats establish liveness. SSE refreshes views; no recurring sandbox or HTTP health probes run.

Back up `submission_files` together with PostgreSQL and task/lab volumes. Workers mount source/task volumes read-only. Remove unreferenced source artifacts with `docker compose run --rm api python -m cjudge.submissions.files`; its database lock prevents racing accepted uploads. It never removes referenced evidence.

Run the end-to-end gate with the runtime worker stopped:

```sh
CJUDGE_JUDGE_MEMORY_LIMIT=2g docker compose run --rm -e CJUDGE_SANDBOX_INSTANCES=2 \
  -v ./tests:/app/tests:ro -v ./migrations:/app/migrations:ro \
  -v ./alembic.ini:/app/alembic.ini:ro worker python -u tests/judging_gate.py
```

The gate uses a disposable database and temporary artifacts. It checks all verdicts, recovery after killing a worker, deadline admission, secrecy, feedback policy, and admin SSE revocation. On September 30, 2026, Ryzen 5 7430U (6 cores/12 threads), 15 GiB RAM, Linux/cgroup v2, two workers capped at 2 GiB: 150 integer-sum submissions with ten cases each uploaded in 1.30 seconds and finished in 17.83 seconds. This simple fixture is not the full M9 performance acceptance test; timeout-heavy behavior is tested separately for correctness.

## M6 marks and corrections

Apply `alembic upgrade head` with API/worker stopped after rebuilding their images, then restart both. Migration `20261001_marks` backfills official results and adds mutable review/batch state separately from immutable submission evidence.

Admin lab overview and student/task pages show official best marks, rounded half-up to two decimals. Totals sum displayed task marks. Pending work keeps prior marks provisional; students with no active submissions receive 0.00. Student/task attempt lists default to best-first, with pending and deleted records last; the lab-wide list stays newest-first.

Open a submission to delete/restore it with a reason, rejudge it, retry delayed work, or inspect retained runs and case inputs. Rejudges preserve earlier official results until success and do not consume upload slots. Network flags compare all retained lab evidence; missing MACs are ignored and differences are not proof of a PC switch. Trusted MAC capture remains planned.

For corrections, publish a revision in the task library, then select it on the assigned task page. New uploads use that revision; old task URLs still open the current task, and previously accepted upload retries retain their original revision/key. Existing active submissions form a correction batch. Official results switch together after active members resolve; infrastructure faults block publication until repaired/retried. Deleting a member removes it from the publication gate; restoring it adds it back or queues current-revision judging after publication. Post-release corrections require a warning and reason and never reopen a lab. M8 student detail reads require release, reveal, ownership and a valid binding.

For real sandbox rejudging, stop the runtime worker and run:

```sh
docker compose stop worker
docker compose run --rm -v ./tests:/app/tests:ro -v ./migrations:/app/migrations:ro \
  -v ./alembic.ini:/app/alembic.ini:ro worker python tests/marks_gate.py --sandbox
docker compose up -d worker
```

The gate uses a disposable database and temporary artifacts. It covers migration backfill, exact marks/ties, deletion/restoration, CSRF/role separation, fault recovery, superseded workers, correction races and publication, and real isolate execution.

## M7 Python authoring

Rebuild API/web/worker, stop API/worker, run `docker compose run --rm api alembic upgrade head`, then restart services. Migration `20261002_authoring` adds durable generation jobs. Back up the new `authoring_files` volume with PostgreSQL; both API and worker images initialize its owner to UID 10001, mode 700.

Admin → Task Library → draft: select Python checker and save source. `read_input()`, `read_output()`, `read_answer()` return bytes; call `accept()` or `reject()`. Print output, exceptions, missing verdicts, and resource failures block judging instead of awarding zero. Review shows the retained checker source; publication freezes it.

In Generate cases, paste Python/C generator and reference C source, choose starting seed/count, and start generation. Each invocation receives seed in `argv[1]`; Python `random` is seeded automatically. Generator stdout is reference stdin; reference stdout is the answer. Keep author programs deterministic. Sources/configuration, seeds, SHA-256 hashes, diagnostics, and checkpoints are retained. Sources are bounded to 64 KiB, inputs/answers to 1 MiB each, combined cases to 16 MiB.

Review generated input/answer previews, then Apply reviewed cases to append to existing draft cases. Publish separately. Editing the draft during generation prevents applying stale results; discard and generate again. One unresolved job per task; failed jobs support retry/discard. Existing manually reviewed cases remain publishable while generation runs. Applied/discarded evidence stays retained; automatic authoring-file cleanup is not implemented.

Generation shares configured sandboxes at lowest priority and yields after each case. Isolates shows Generating work and lease health. Crashes resume checkpoints; three infrastructure faults require admin retry, while confirmed teacher errors fail immediately.

Run the module gate with runtime workers stopped:

```sh
docker compose stop worker
docker compose run --rm -v ./tests:/app/tests:ro -v ./migrations:/app/migrations:ro \
  -v ./alembic.ini:/app/alembic.ini:ro worker python tests/authoring_gate.py --sandbox
docker compose up -d worker
```

The disposable gate verifies real byte helpers/AC/WA/faults, full student output, reproducible Python/C seeds, reference failures, authorization/CSRF, staged apply/publication, lease fencing, bounded retries, and live worker kill/restart recovery. `api python tests/authoring_gate.py` runs its database/API checks without isolate.


## M8 stop, release and exports

Rebuild API/web/worker, stop API/worker, run `docker compose run --rm api alembic upgrade head`, then restart services. M8 adds migrations through `20261005_delete` and protected `export_files` (API UID 10001, mode 700); back it up with PostgreSQL and other artifact volumes.

On a running lab overview, **Stop now** requires confirmation and a reason. It closes new uploads at server time; accepted uploads keep judging. Reopen is allowed only before first release.

After the lab ends, resolve active judging/rejudge/correction jobs before **Release results**. Retry infrastructure faults or exclude attempts with an audited soft deletion. Reused scheduled tests require acknowledgment, including visible post-release corrections. **Hide results** blocks student source/details without undoing past disclosure; first release permanently prevents reopening.

Students open their own submissions from task/lab history while reveal is enabled. Detail pages show escaped source, official marks, retained grading runs and failed-case input/expected/stdout/stderr previews (64 KiB each, labeled when truncated). Binding, ownership and visibility are checked on every read. Network metadata and infrastructure diagnostics remain admin-only.

**Download final CSV** uses official marks and safe spreadsheet cells; XLSX and scoreboards are deferred. **Archive lab** freezes lab/grading edits. **Generate lab ZIP** is separate and includes retained/deleted evidence, PDF versions, revision tests/configurations, marks and audits. `manifest.json` format version 1 records entry sizes/hashes; `snapshot.json` stores byte streams as Base64 objects. Verify the downloaded ZIP against the displayed SHA-256 and keep a saved copy. ZIPs are not server backups and import is unsupported.

Permanent deletion requires an archived lab, a current verified export, saved-copy acknowledgment, typed lab title and audit reason. It preserves global accounts/shared tasks and deletion audits. File failures leave retry records: send authenticated, CSRF-protected `POST /api/admin/labs/<lab-id>/cleanup` to retry. Unreferenced export ZIPs after interrupted/uncertain commits remain protected; M9 will define retention/capacity operations.

```sh
docker compose run --rm -v ./tests:/app/tests:ro api python tests/release_gate.py
```

The disposable M8 gate checks fresh/existing migration paths, stop/version races, upload recovery, release/reuse rules, student binding/ownership/secrecy, retained runs, previews, CSV safety, ZIP hashes/completeness, deletion protections and cleanup recovery. It does not execute student programs.

## M9 acceptance and operations

Automated acceptance passed on October 1, 2026: API p95 33.594 ms overall, at most 36.682 ms per endpoint; 150 representative uploads finished in 63.620 seconds; five light tasks each finished below one second. All module gates passed. Configuration, fixture hashes, timeout measurements, and remaining manual checks are recorded in [context/acceptance-results.json](context/acceptance-results.json).

The API image runs four Uvicorn processes to use multiple CPU cores. Each process keeps the existing 5+5 database connection pool: at most 40 pooled API connections plus four event listeners. PostgreSQL's 200-connection budget also covers the maximum 32 sandbox workers. Password hashing remains bounded to four concurrent operations per API process.

Build current API/web/worker/key-init images before testing. Run backend/frontend checks first, then:

```sh
python scripts/acceptance.py /tmp/cjudge-m9-results.json
```

After module gates have passed, use `--performance-only` to repeat measurements without rerunning those gates. The report explicitly marks module gates as not rerun.

Forced process/host termination may prevent cleanup. The report records the disposable project name. Remove only that `cjudge-m9-*` project with `docker compose -p <test-project> -f compose.yaml -f deploy/acceptance.yaml --profile judging --profile setup down --volumes`, then restart normal workers with `docker compose --profile judging up -d worker`. Never run volume deletion against the normal project.

The command temporarily stops running sandbox services to prevent isolate-box conflicts, uses a uniquely named Compose project with fresh volumes, and restores those services on exit. The normal web/API/database stay available. It uses the existing trusted localhost certificate and current sandbox count/memory limit. Database and artifact volumes from the normal project are never mounted. Acceptance containers use internal networks with no external routing or published ports. The host reaches nginx directly through its internal bridge address over verified HTTPS, with localhost Host/Origin. Normal operation needs no internet, but installation/builds may.

The gate runs identity/task/lab/submission/release checks and real isolate, judging, marks, and authoring gates before performance measurement. It uses 170 seeded test sessions/bindings, five deterministic tasks, and ten cases/task. Setup/login is excluded from latency measurement. After populating histories, 150 concurrent clients each issue one request/second for 120 measured requests following warm-up; the four endpoints are lab snapshot, filtered task history, lab history, and individual status. Overall and per-endpoint p95 must be below 300 ms. Five light-load programs must each finish within 30 seconds. A fresh 150-upload burst spans 60 seconds and must finish within five minutes of first acceptance. Fifteen infinite-loop programs measure timeout-heavy behavior separately. All C execution remains inside isolate. JSON results contain no credentials or source code.

Restart checks retain accepted work and grading results; SSE is opened and reconnected through nginx. Module gates verify killed-worker recovery, stale-result fencing, disk-write rollback, missing artifacts, and audited admin actions. A real second-device browser check with WAN disconnected remains a manual release prerequisite: verify certificate trust, login/logout, entry, PDF download, upload, and live announcements while LAN stays connected. Container egress isolation does not establish Wi-Fi reachability or browser trust.

Before each lab, check server time (`timedatectl status`), disk space (`df -h`), Docker volume usage (`docker system df -v`), and Isolates. Reserve the server's DHCP address. Inspect certificate expiry with `openssl x509 -in certs/server.crt -noout -enddate`; renew before expiry using the LAN SAN command, recreate web, and distribute updated public trust. Never share private keys.

Keep at least 20% disk headroom. Estimate storage from attempts and retained rejudges, not student count alone: budget at least 2 MiB per ten-case run for source/diagnostics and database overhead, then add test revisions, PDFs, generation artifacts, ZIP copies, and PostgreSQL WAL. Large checker diagnostics and retained versions need extra allowance. Review capacity before another lab; no automatic cleanup runs.

On storage failure, free space without deleting retained evidence, check volume permissions, restore missing files from a consistent backup if available, and retry delayed jobs from admin. Never convert infrastructure failures to zero marks. Restart worker to recover leases; inspect sanitized Isolates faults and container logs. Stop API/worker before migrations; run migrations before restarting them. Do not run sandbox gates beside runtime workers.

For a consistent manual server backup, stop API/worker writes, dump PostgreSQL, and preserve matching `credential_keys`, `task_files`, `lab_files`, `submission_files`, `authoring_files`, and `export_files` volumes with ownership/permissions intact. Store backups outside the repository and protect credentials/student evidence. Restore the dump and matching artifacts together into a disposable deployment and verify before using them. Automated backup/restore remains out of scope; a lab ZIP alone is insufficient.

The lab admin preserves verified downloaded ZIPs before permanent deletion. Retain teacher authoring evidence and files referenced by database records. Do not blindly prune Docker volumes or protected files. After an interrupted export, unreferenced ZIPs may remain; identify them against export receipts while writes are stopped and preserve them until their status is reviewed. No scheduled retention policy or automatic orphan deletion is implemented.

## M10 Lab Scoreboard

Each admin lab has a **Scoreboard** page. **Visible to participants** defaults off; enabling it reveals live marks/times before release. Participants open only their own submission links; source and case details retain existing release gates. Frozen students still count. Ranking uses total marks descending, then the sum of elapsed acceptance times of positive-score counted tasks ascending, without failed-attempt penalties. Boxes use muted partial/judging/solved/first-solve shades; pending work is provisional.

Update an existing installation:

```sh
docker compose --profile judging stop api worker
docker compose build api web worker
docker compose run --rm api alembic upgrade head
docker compose --profile judging up -d web worker
```

Backend checks: `uv run pytest -q`. Frontend checks: `npm run test --prefix src/frontend` and `npm run build --prefix src/frontend`. The expanded database gate is `tests/marks_gate.py`; it creates/drops its own database and does not execute submitted code:

```sh
docker compose run --rm -e CJUDGE_PUBLIC_ORIGIN=https://localhost:8443 -e CJUDGE_ALLOWED_HOSTS=localhost,127.0.0.1 -v ./tests:/app/tests:ro api python tests/marks_gate.py
```
