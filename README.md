# cJudge

Offline C lab judge. M0 provides an HTTPS frontend and a database-backed API readiness check. M1 adds an isolated runner. Login, submissions, and grading UI are future modules.

## Local setup

Requires Docker Compose, OpenSSL, and Node.js for local frontend checks.

1. Copy `.env.example` to `.env`. Replace `POSTGRES_PASSWORD` with a long random alphanumeric value. Set `CJUDGE_UID` and `CJUDGE_GID` to your `id -u` and `id -g` output.
2. Run `sh scripts/create-cert.sh localhost`. For a LAN name or IP, pass its certificate subject and SAN list, for example `sh scripts/create-cert.sh cjudge.lab 'DNS:localhost,IP:127.0.0.1,DNS:cjudge.lab'`.
3. Run `docker compose up -d --build`.
4. Run `docker compose exec api alembic upgrade head` and `sh scripts/smoke.sh`.
5. Open `https://localhost:8443`; trust `certs/server.crt` in the lab browsers before real use. The default certificate is self-signed.

Only localhost ports 8080 and 8443 are published. To serve a LAN, change the web port bindings, add the LAN hostname to `CJUDGE_ALLOWED_HOSTS`, and create a certificate with that hostname/IP in its SAN list. Keep `api` and `db` private.

Stop services with `docker compose down`. The PostgreSQL volume survives container recreation; `docker compose down --volumes` deletes it.

## Checks

- Backend: `uv sync --locked && uv run pytest -q`
- Frontend: `npm ci --prefix frontend && npm run test --prefix frontend && npm run build --prefix frontend`
- Compose: `docker compose config --quiet && docker compose up -d --build && sh scripts/smoke.sh`

The source of truth for product behavior and implementation modules is in `context/`.

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

`Result` includes verdict, bounded full stdout, first 64 KiB of stderr, CPU/wall seconds, and peak memory in KiB. `stdout_preview` returns the first 64 KiB. `OK` means execution succeeded; AC/WA comparison arrives in M3. Student failures map to CE/RE/TLE/MLE/OLE. Checker and infrastructure failures raise `SandboxError`, never a student score. MLE requires a confirmed cgroup OOM kill; allocation failure without OOM is handled by the program and may produce RE.

Defaults follow `context/technical-requirements.md`. Temporary storage is 64 MiB (128 MiB for compilation), capped at 1,024 inodes. Stderr is capped at 1 MiB; compiler stdout at 1 MiB; checker stdout at 64 KiB. Source is capped at 64 KiB, stdin at 10 MiB, and staged files at 16 MiB. Full output is available for future comparison before preview truncation. One locked sandbox runs at a time; writable state and cgroups are removed after every run.
