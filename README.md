# cJudge

Offline C lab judge. M0–M4 provide HTTPS, isolation, accounts, tasks, and labs. M5 adds durable C submissions, fair asynchronous judging, a configurable sandbox pool, and an admin Isolates panel. M6 adds official marks, audited deletion/restoration, rejudge history, and atomic task corrections. Python authoring and release/export remain planned.

## Repository layout

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

Only localhost ports 8080 and 8443 are published. To serve a LAN, change web port bindings, add the LAN hostname to `CJUDGE_ALLOWED_HOSTS`, set `CJUDGE_PUBLIC_ORIGIN` to the exact browser origin (including port), and create a certificate with that hostname/IP in its SAN list. Keep `api` and `db` private.

Stop services with `docker compose down`. The PostgreSQL volume survives container recreation; `docker compose down --volumes` deletes it.

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

For corrections, publish a revision in the task library, then select it on the assigned task page. New uploads use that revision; old task URLs still open the current task, and previously accepted upload retries retain their original revision/key. Existing active submissions form a correction batch. Official results switch together after active members resolve; infrastructure faults block publication until repaired/retried. Deleting a member removes it from the publication gate; restoring it adds it back or queues current-revision judging after publication. Post-release corrections require a warning and reason and never reopen a lab. Student marks/details remain unavailable until M8.

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

Review generated input/answer previews, then Apply reviewed cases to replace draft cases. Publish separately. Editing the draft during generation prevents applying stale results; discard and generate again. One unresolved job per task; failed jobs support retry/discard. Existing manually reviewed cases remain publishable while generation runs. Applied/discarded evidence stays retained; automatic authoring-file cleanup is not implemented.

Generation shares configured sandboxes at lowest priority and yields after each case. Isolates shows Generating work and lease health. Crashes resume checkpoints; three infrastructure faults require admin retry, while confirmed teacher errors fail immediately.

Run the module gate with runtime workers stopped:

```sh
docker compose stop worker
docker compose run --rm -v ./tests:/app/tests:ro -v ./migrations:/app/migrations:ro \
  -v ./alembic.ini:/app/alembic.ini:ro worker python tests/authoring_gate.py --sandbox
docker compose up -d worker
```

The disposable gate verifies real byte helpers/AC/WA/faults, full student output, reproducible Python/C seeds, reference failures, authorization/CSRF, staged apply/publication, lease fencing, bounded retries, and live worker kill/restart recovery. `api python tests/authoring_gate.py` runs its database/API checks without isolate.
