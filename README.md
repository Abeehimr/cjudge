# cJudge

Offline C lab judge. M0 provides an HTTPS frontend and database. M1 adds an isolated runner. M2 adds global student accounts and login. M3 adds an admin task library with immutable grading revisions. M4 adds labs, browser binding, protected PDFs, and live announcements. Submissions remain M5.

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
- Frontend: `npm ci --prefix frontend && npm run test --prefix frontend && npm run build --prefix frontend`
- Compose: `docker compose config --quiet && docker compose up -d --build web && sh scripts/smoke.sh`
- Identity gate: `docker compose run --rm -v ./tests:/app/tests:ro api python tests/identity_gate.py`
- Task gate: `docker compose run --rm -v ./tests:/app/tests:ro api python tests/tasks_gate.py`
- Lab gate: `docker compose run --rm -v ./tests:/app/tests:ro api python tests/labs_gate.py`

Compose has no periodic health probes. Run `sh scripts/smoke.sh` when you want a readiness check.

The source of truth for product behavior and implementation modules is in `context/`.

## M2 accounts

Student accounts are global: each roll number keeps one password across labs. Admin can add students manually or import UTF-8 CSV with `roll_number,name` headers, up to 1 MiB/1,000 rows. Existing roll numbers keep their name/password; name mismatches are reported. Admin can edit names, reveal/print selected credentials, and reset student passwords. Students cannot change passwords. Enroll global accounts from Admin → Labs.

Admin password is hash-only. Student passwords are hashed for login and separately encrypted for admin reprints. Keep the `credential_keys` Docker volume with database backups; losing it makes existing student passwords unrecoverable. The API mounts that volume read-only. `key-init` refuses to overwrite an existing key. Never copy the key, password sheets, or `.env` into Git. To reset the admin password, run `docker compose run --rm api python -m cjudge.identity reset-admin`; existing admin sessions are revoked.

Sessions last eight hours. Logout and password resets revoke sessions. Login is rate-limited per account, while nginx allows a shared lab IP burst. Credential responses are not cached. No public registration exists.

## M3 task library

After updating an existing installation, run `docker compose build api web`, then `docker compose run --rm api alembic upgrade head` and `docker compose up -d web`. Under **Admin → Tasks**, create a draft, add pasted cases or a ZIP of flat `N.in`/`N.out` pairs, review settings/cases, and publish a revision. Task statements are optional Markdown; HTML and embedded images do not render. Case downloads remain admin-only; lab students see statements and public resource limits. Judging remains M5.

ZIPs are limited to 17 MiB compressed, 16 MiB expanded, 100 paired cases, and 1 MiB per input/answer. Exact checking compares bytes, optionally ignoring one final LF/CRLF. Token checking splits ASCII whitespace, with optional case and finite-number tolerances. `src/cjudge/task_grading.py` defines both comparison and rational scoring for M5. Published revisions retain their original configuration and cases. Draft edits use version checks and may return 409; reload before retrying.

The `task_files` volume contains protected case sets and must be backed up with PostgreSQL. Losing it makes published tests unavailable. Replacing draft cases can leave unreferenced files after interrupted transactions; keep the volume until archive/cleanup support arrives.

## M4 labs

Upgrade with `docker compose build api web`, `docker compose run --rm api alembic upgrade head`, then `docker compose up -d web`.

Under **Admin → Labs**, create a lab, assign ordered published revisions, enroll students, and upload lab PDFs. Schedule a future start or choose **Start now**. At least one task/student is required; PDFs may be omitted only when every task has a Markdown statement. Overlapping lab windows are rejected. Task assignments and enrollment removals close at start; late additions remain available.

Students select their assigned lab and explicitly **Enter lab** after start. This binds the browser; missing cookies require admin release even at the same IP. Release revokes all that student's sessions. Strict IP matching defaults off; otherwise IP changes are allowed and flagged. Browser binding remains required after the lab ends.

Test announcements and PDF replacement with a student tab open: SSE refreshes materials and deadlines. Previous PDFs remain admin-only. Test **Freeze/Unfreeze**, browser release, whole-lab extension, and pre-release reopening; reasons are audited. Freeze affects future submission admission in M5, while materials stay readable. No upload/judging screen exists yet.

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

Only `judge` receives `SYS_ADMIN`, `SYS_RESOURCE`, `NET_ADMIN` (to bring up the sandbox's loopback interface), and an unconfined **outer** seccomp profile; isolate applies its own syscall restrictions inside each sandbox. The service is not privileged, exposes no ports, mounts no host directories or Docker socket, and receives no application credentials. Its root filesystem is read-only, with a 1 GiB memory ceiling and no swap.

The entrypoint mounts the container's private cgroup v2 namespace, moves itself into `manager`, and enables CPU/memory/PID controllers. It never mounts the host cgroup tree. Inner programs use UID/GID 60000 with no capabilities. Compilation may spawn 32 processes; other profiles allow one. Run one judge container at a time: parallel containers need distinct UID ranges before M5 scaling.

Use `docker compose run`, not `exec`: moving the container's main process enables controller delegation, but Docker cannot insert an exec process into the now-internal cgroup. No host configuration is changed by setup. If mounts or controller delegation fail, fix the host policy; there is no unsandboxed fallback. See [upstream isolate installation guidance](https://www.ucw.cz/isolate/isolate.1.html).

Host crash collectors are outside container limits. If `cat /proc/sys/kernel/core_pattern` starts with `|`, configure the host collector to discard sandbox core dumps before accepting real submissions. For systemd-coredump, `Storage=none` and `ProcessSizeMax=0` disable dump storage/processing host-wide; apply that policy only on the dedicated judge host. `--core=0` alone does not disable a piped host collector. See [coredump.conf(5)](https://www.man7.org/linux/man-pages/man5/coredump.conf.5.html).

### Runner contract

Worker-only functions live in `src/cjudge/runner.py`: `compile_c(source)` returns an executable on success; `execute(executable, stdin, limits)` runs one fresh case; `run_python(script, profile, files)` isolates checker/generator code. Python authoring protocols remain M7 work. Inputs are bytes and supplied filenames must be plain basenames.

`Result` includes verdict, bounded full stdout, first 64 KiB of stderr, CPU/wall seconds, and peak memory in KiB. `stdout_preview` returns the first 64 KiB. `OK` means execution succeeded; AC/WA comparison is defined in M3 and wired to judging in M5. Student failures map to CE/RE/TLE/MLE/OLE. Checker and infrastructure failures raise `SandboxError`, never a student score. MLE requires a confirmed cgroup OOM kill; allocation failure without OOM is handled by the program and may produce RE.

Defaults follow `context/technical-requirements.md`. Temporary storage is 64 MiB (128 MiB for compilation), capped at 1,024 inodes. Stderr is capped at 1 MiB; compiler stdout at 1 MiB; checker stdout at 64 KiB. Source is capped at 64 KiB, stdin at 10 MiB, and staged files at 16 MiB. Full output is available for future comparison before preview truncation. One locked sandbox runs at a time; writable state and cgroups are removed after every run.
