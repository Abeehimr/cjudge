# Repository Guidelines

## Project Structure & Module Organization

This repository contains a minimal Python scaffold for cJudge, a planned offline C programming lab judge.

- `src/cjudge/`: Python package; `__init__.py` defines the CLI entry point.
- `pyproject.toml`: package metadata, Python requirement, build backend, and console script.
- `cJudge_plan_v1.md`: proposed requirements, architecture, and milestones.
- `README.md`: project documentation; expand it as usable features arrive.

There are no tests, frontend assets, or implemented judging services yet. Treat the architecture in the plan as proposed rather than existing functionality.

## Build, Test, and Development Commands

Use Python 3.14 or newer and uv:

- `uv sync`: create or synchronize the development environment.
- `uv run cjudge`: run the console entry point, currently a greeting.
- `uv build`: build source and wheel distributions.

No test, lint, or formatting commands are configured. Add their dependencies and configuration before documenting them as available.

## Coding Style & Naming Conventions

Use four-space indentation and conventional Python naming: `snake_case` for modules and functions, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants. Add type annotations to new function interfaces, following the existing entry point.

Keep modules focused and place application logic inside `src/cjudge/`. Declare dependencies in `pyproject.toml`. No formatter or linter is currently enforced.

## Testing Guidelines

No testing framework or coverage threshold exists yet. When adding substantive behavior, establish tests under `tests/`, using `test_*.py` filenames, and document the chosen runner and command.

Prioritize grading correctness, deadline boundaries, authorization, and worker recovery as those features arrive. Sandbox integration tests should document required Linux tooling.

## Commit & Pull Request Guidelines

The sole existing commit uses an imperative, descriptive subject: “Initialize the CJudge project structure and requirements.” Follow that style; no stricter convention is established.

Pull requests should explain the problem, resulting behavior, validation performed, and relevant plan milestone or issue. Include screenshots for UI changes and document configuration or migration requirements.

## Security & Configuration

Never execute submitted student programs directly on the host without sandbox isolation. Implement the planned sandbox boundary before supporting execution. Keep credentials, student submissions, hidden test data, and local environment files out of commits.
