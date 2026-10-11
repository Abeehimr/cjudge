# Docker Deployment

Current deployment is defined in [`compose.yaml`](../compose.yaml). The application uses four runtime services, one standalone isolation gate, and one setup service. Only `web` publishes host ports.

| Service | Role | Network | Host ports | Persistent access |
| --- | --- | --- | --- | --- |
| `web` | nginx serves built React files, redirects HTTP to HTTPS, proxies API/SSE | default | `${CJUDGE_BIND_ADDRESS}:8080`, `:8443` | `certs/` read-only |
| `api` | Four Uvicorn processes; auth, labs, tasks, uploads, exports, SSE | default | none | Credential key read-only; task, lab, submission, authoring, export files read/write |
| `db` | PostgreSQL 17, persistent metadata and queue | default + internal `judge_queue` | none | `postgres_data` |
| `worker` | Leased judging/generation pool; starts `CJUDGE_SANDBOX_INSTANCES` isolate slots | internal `judge_queue` | none | Task/submission files read-only; authoring files read/write |
| `judge` | Standalone M1 isolation gate (`sandbox` profile) | none | none | none |
| `key-init` | Creates student credential encryption key once (`setup` profile) | default | none | `credential_keys` read/write |

`web`, `api`, and `db` start without profiles. Start `worker` with the `judging` profile. The standalone `judge` uses `network_mode: none`; it does not connect to the app or database. `key-init` runs only during initial setup. `db` bridges the default and internal queue networks; the worker cannot reach nginx/API through Compose networking. The API and worker coordinate through PostgreSQL tables and notifications.

## Persistent storage

| Volume | Contents | Mounted by |
| --- | --- | --- |
| `postgres_data` | Accounts, labs, queue, grading and audit metadata | `db` |
| `credential_keys` | Student password encryption key | `key-init` write; `api` read-only |
| `task_files` | Published test case ZIPs | `api` write; `worker` read-only |
| `lab_files` | Protected lab PDFs | `api` write |
| `submission_files` | Accepted student source | `api` write; `worker` read-only |
| `authoring_files` | Generator/reference source and staged cases | `api`, `worker` write |
| `export_files` | Verified lab archive ZIPs | `api` write |

Back up PostgreSQL with **all matching volumes**, especially `credential_keys`; a lab export is not a server backup. Files use application-generated paths and are never directly exposed by nginx. The API runs as UID 10001; the worker image prepares its writable authoring directory. Do not delete volumes to stop the app.

## Sandbox boundary

`worker` and `judge` are rootful Linux containers with private cgroup namespaces and limited added capabilities (`SYS_ADMIN`, `SYS_RESOURCE`, `NET_ADMIN`). Their outer seccomp profile is unconfined so `isolate` can configure inner sandboxes. Root filesystems are read-only, writable scratch is tmpfs, memory is bounded, and no Docker socket is mounted. Each worker slot uses its own isolate box/UID. The inner isolate restricts submitted and authoring programs; Docker network separation alone is not the execution sandbox. Never run the standalone `judge` gate at the same time as runtime workers because box UID ranges overlap.

## Commands

From repository root, configure `.env` and certificates first; see [README](../README.md#local-setup).

```sh
# First installation only: build image and create the key, then migrate.
docker compose build api key-init web worker
docker compose run --rm key-init
docker compose up -d db
docker compose run --rm api alembic upgrade head

# Normal service start/restart; --build applies source/image changes.
docker compose --profile judging up -d --build web worker
docker compose --profile judging ps

# Stop every service, including profiled workers. Keep named volumes.
docker compose --profile judging --profile sandbox --profile setup down --remove-orphans
```

Create the admin account before first login with `docker compose run --rm api python -m cjudge.identity create-admin`. After an IP or environment change, recreate affected services: `docker compose --profile judging up -d --force-recreate web api worker`. For a database migration, stop API/worker writes, run `docker compose run --rm api alembic upgrade head`, then start them again. Verify readiness on demand with `sh scripts/smoke.sh`; Compose does not run periodic health probes.

`docker compose down --volumes` **deletes all named volumes and application data**. Use it only for a disposable deployment. If Docker reports `cjudge_judge_queue Resource is still in use`, list containers with `docker ps --filter network=cjudge_judge_queue`; stop any remaining Compose project or one-off container before repeating `down`. Do not remove a live network manually.
