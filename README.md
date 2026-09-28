# cJudge

Offline C lab judge. M0 currently provides an HTTPS frontend and a database-backed API readiness check. Judging and login are future modules.

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
