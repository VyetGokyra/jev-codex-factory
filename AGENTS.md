# Repository Guidelines

## Project Structure & Module Organization

This repository is currently a minimal scaffold. Keep executable automation in `scripts/` and automated checks in `tests/`. Treat `logs/` and `state/` as runtime-output directories, not as locations for source code. Add application code under a clearly named top-level directory such as `src/` when implementation begins, and mirror its module layout under `tests/` where practical.

Do not commit generated logs, transient state, credentials, or machine-specific files. Update `.gitignore` when introducing tools that create such artifacts.

## Build, Test, and Development Commands

No build system or package manager is configured yet. Until one is added, inspect and run repository scripts explicitly, for example:

```sh
./scripts/<task-name>
```

When adding a toolchain, expose a small, documented command set through a conventional entry point such as `Makefile`, `package.json`, or `pyproject.toml`. Prefer predictable commands such as `make test`, `npm test`, or `pytest`, and update this guide in the same change.

## Coding Style & Naming Conventions

Follow the formatter and linter standard for the language introduced; commit their configuration so results are reproducible. Use spaces rather than tabs unless the formatter requires otherwise. Name scripts and files descriptively with lowercase `kebab-case` or the language's established convention. Use `snake_case` for Python functions and modules, `PascalCase` for classes, and clear verb-first names for scripts (for example, `scripts/refresh-state`).

Keep functions focused, avoid hidden dependencies on local environment state, and document required environment variables.

## Testing Guidelines

Place tests in `tests/` and name them after the behavior or module under test (for example, `tests/test_state_store.py`). Every bug fix should include a regression test; new behavior should cover success paths and important failures. Tests must be deterministic and must not rely on committed contents of `logs/` or `state/`.

## Commit & Pull Request Guidelines

There is no existing commit history to establish a house style. Use concise, imperative commit subjects, optionally following Conventional Commits (for example, `feat: add state loader` or `test: cover invalid config`). Keep commits focused.

Pull requests should explain the motivation, summarize the implementation, list verification commands, and link relevant issues. Include screenshots or sample output for user-visible changes. Call out new configuration, environment variables, migrations, or operational risks explicitly.
