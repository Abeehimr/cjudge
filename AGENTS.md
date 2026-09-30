# Repository Guidelines

## Project Structure & Module Organization

This repository is building cJudge, an offline C programming lab judge.

- `src/cjudge/`: Python package; feature packages are `identity/`, `tasks/`, and `labs/`; `api.py` assembles routes.
- `src/frontend/`: React/TypeScript app and component tests.
- `deploy/`: nginx configuration and judge container configuration/entrypoint.
- `migrations/`: Alembic migration environment and future revisions.
- `pyproject.toml`: package metadata, Python requirement, build backend, and console script.
- `context/`: product requirements, design, technical requirements, and module checklist.
- `README.md`: local setup and checks.

M1 has a standalone sandbox runner. M2 has global accounts and sessions. M3 has admin task drafts and published revisions. M4 has labs, protected PDFs, and browser binding. Submissions remain planned.

## Build, Test, and Development Commands

Use Python 3.14 or newer and uv:

- `uv sync`: create or synchronize the development environment.
- `uv run cjudge`: run the console entry point, currently a greeting.
- `uv build`: build source and wheel distributions.

- `uv run pytest -q`: run backend tests.
- `npm run test --prefix src/frontend`: run frontend tests.
- `npm run build --prefix src/frontend`: type-check and build frontend.
- `docker compose up -d --build web`: start web, API, and database after M2 setup in `README.md`.
- `docker compose run --rm judge`: run the M1 isolation gate in a temporary container.
- `docker compose run --rm -v ./tests:/app/tests:ro api python tests/identity_gate.py`: run M2 integration checks.
- `docker compose run --rm -v ./tests:/app/tests:ro api python tests/tasks_gate.py`: run M3 integration checks.
- `docker compose run --rm -v ./tests:/app/tests:ro api python tests/labs_gate.py`: run M4 integration checks.

## Coding Style & Naming Conventions

Use four-space indentation and conventional Python naming: `snake_case` for modules and functions, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants. Add type annotations to new function interfaces, following the existing entry point.

Keep modules focused and place application logic inside `src/cjudge/`. Declare dependencies in `pyproject.toml`. No formatter or linter is currently enforced.

## Testing Guidelines

Backend uses pytest under `tests/test_*.py`; frontend uses Vitest under `src/frontend/src/*.test.tsx`. Real-database gates are `tests/identity_gate.py` (M2), `tests/tasks_gate.py` (M3), and `tests/labs_gate.py` (M4). No coverage threshold is set. Complete each module gate before starting its dependents.

Prioritize grading correctness, deadline boundaries, authorization, and worker recovery as those features arrive. Sandbox integration tests should document required Linux tooling.

## Commit & Pull Request Guidelines

Use imperative, descriptive commit subjects, as in recent module commits. No stricter convention is established.

Pull requests should explain the problem, resulting behavior, validation performed, and relevant plan milestone or issue. Include screenshots for UI changes and document configuration or migration requirements.

Work one module at a time. Divide it into small tested commits; stop at each module gate for review. Apply Ponytail and Caveman skills, and consult security-best-practices for new Python/TypeScript code.

## Security & Configuration

Never execute submitted student programs directly on the host without sandbox isolation. Implement the planned sandbox boundary before supporting execution. Keep credentials, student submissions, hidden test data, and local environment files out of commits. Back up the `task_files` volume with PostgreSQL; task case data is not in the database.
