# Repository Guidelines

## Project Structure & Module Organization

This repository is building cJudge, an offline C programming lab judge.

- `src/cjudge/`: Python package; `__init__.py` defines the CLI entry point.
- `frontend/`: React/TypeScript app and component tests.
- `judge/`: isolate configuration and container entrypoint.
- `migrations/`: Alembic migration environment and future revisions.
- `pyproject.toml`: package metadata, Python requirement, build backend, and console script.
- `context/`: product requirements, design, technical requirements, and module checklist.
- `README.md`: local setup and checks.

M1 has a standalone sandbox runner. Submission handling, scoring, and most architecture in `context/` remain planned.

## Build, Test, and Development Commands

Use Python 3.14 or newer and uv:

- `uv sync`: create or synchronize the development environment.
- `uv run cjudge`: run the console entry point, currently a greeting.
- `uv build`: build source and wheel distributions.

- `uv run pytest -q`: run backend tests.
- `npm run test --prefix frontend`: run frontend tests.
- `npm run build --prefix frontend`: type-check and build frontend.
- `docker compose up -d --build`: start M0 services after creating `.env` and local certificates as described in `README.md`.
- `docker compose run --rm judge`: run the M1 isolation gate in a temporary container.

## Coding Style & Naming Conventions

Use four-space indentation and conventional Python naming: `snake_case` for modules and functions, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants. Add type annotations to new function interfaces, following the existing entry point.

Keep modules focused and place application logic inside `src/cjudge/`. Declare dependencies in `pyproject.toml`. No formatter or linter is currently enforced.

## Testing Guidelines

Backend uses pytest under `tests/test_*.py`; frontend uses Vitest under `frontend/src/*.test.tsx`. No coverage threshold is set. Complete the test gate for each module before starting its dependents.

Prioritize grading correctness, deadline boundaries, authorization, and worker recovery as those features arrive. Sandbox integration tests should document required Linux tooling.

## Commit & Pull Request Guidelines

The sole existing commit uses an imperative, descriptive subject: “Initialize the CJudge project structure and requirements.” Follow that style; no stricter convention is established.

Pull requests should explain the problem, resulting behavior, validation performed, and relevant plan milestone or issue. Include screenshots for UI changes and document configuration or migration requirements.

Work one module at a time. Divide it into small tested commits; stop at each module gate for review. Apply Ponytail and Caveman skills, and consult security-best-practices for new Python/TypeScript code.

## Security & Configuration

Never execute submitted student programs directly on the host without sandbox isolation. Implement the planned sandbox boundary before supporting execution. Keep credentials, student submissions, hidden test data, and local environment files out of commits.
